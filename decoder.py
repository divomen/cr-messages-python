from collections import OrderedDict
from coc.message.reader import CoCMessageReader
from coc.message.definitions import CoCMessageDefinitions
import json
import math
from coc.hexdump import hexdump


class CoCMessageDecoder:
    lengthTypes = ['BYTE', 'INT', 'RRSINT32']
    _bitfield = None

    def __init__(self, definitions=None):
        if not definitions:
            self._definitions = CoCMessageDefinitions.read()
        self._definitions = definitions

    def decodeFile(self, filepath):
        messageid = None
        length = None
        version = None
        payload = None
        with open(filepath, 'rb') as fh:
            messageid = int.from_bytes(fh.read(2), byteorder="big")
            length = int.from_bytes(fh.read(3), byteorder="big")
            version = int.from_bytes(fh.read(2), byteorder="big")
            payload = fh.read(length)
        if messageid and length and payload:
            return self.decode(messageid, version, payload)
        return None

    def decode(self, messageid, unknown, payload):
        if messageid in self._definitions:
            reader = CoCMessageReader(messageid, unknown, payload)
            if "fields" in self._definitions[messageid]:
                decoded = {
                    "id": messageid,
                    "name": self._definitions[messageid]["name"],
                    "fields": self._decode_fields(reader, self._definitions[messageid]["fields"])
                }
            else:
                decoded = {
                    "id": messageid,
                    "name": self._definitions[messageid]["name"]
                }

            unused = reader.read()
            if unused:
                self.dump(decoded)
                raise IndexError("Unused {} bytes in buffer remains".
                                 format(len(unused)))
            return decoded
        else:
            raise KeyError("Message definition missing ({}).".format(messageid))

    def _decode_fields(self, reader, fields):
        decoded = OrderedDict()
        for index, field in enumerate(fields):
            if "name" not in field:
                field["name"] = "unknown_{}".format(str(index).zfill(math.floor(math.log10(len(fields)))))

            # default in lengthType to 4 byte int. Used to count the number of members in an array
            if "lengthType" not in field:
                field["lengthType"] = "INT"

            self._lengthTypeCheck(field["lengthType"])

            value = self._decode_field(reader, field["name"], field["type"], field["lengthType"])
            decoded[field["name"]] = value
        return decoded

    def _lengthTypeCheck(self, lengthType):
        if lengthType not in self.lengthTypes:
            raise ValueError("lengthType {} not supported".format(lengthType))

    def _decode_field(self, reader, name, type, lengthType):
        if not len(reader.peek(1)):
            raise IndexError("Read buffer out of data.")
        if type[:1] == "?":
            if self._bitfield:
                self._bitfield = (self._bitfield << 1) % 16
                if not self._bitfield:
                    return None
            else:
                self._bitfield = 1
            if reader.peek_int(1) & self._bitfield:
                type = type[1:]
                reader.read(1)
                self._bitfield = None
            else:
                return None
        elif self._bitfield:
            reader.read(1)
            self._bitfield = None

        found = type.find("[")
        if found >= 0:
            count = type[found + 1:-1]
            type = type[:found]
            if not count:
                if lengthType == "BYTE":
                    count = reader.read_int(1)
                elif lengthType == "INT":
                    count = reader.read_int(4)
                else:
                    count = reader.read_rrsint32()
            decoded = []
            for i in range(int(count)):
                decoded.append(self._decode_field(reader, "{}[{}]".format(name, i), type, lengthType))
            return decoded
        elif type == "BOOLEAN":
            return bool(reader.read_int(1))
        elif type == "BYTE":
            return reader.read_byte()
        elif type == "SCID":
            return reader.read_scid()
        elif type == "SHORT":
            return reader.read_short()
        elif type == "INT":
            return reader.read_int()
        elif type == "INT32":
            return reader.read_int32()
        elif type == "SINT32":
            return reader.read_sint32()
        elif type == "RRSINT32":
            return reader.read_rrsint32()
        elif type == "RRSLONG":
            return reader.read_rrslong()
        elif type == "LONG":
            return reader.read_long()
        elif type == "STRING":
            return reader.read_string()
        elif type == "ZIP_STRING":
            decoded = reader.read_zstring()
            if not decoded:
                return decoded
            try:
                decoded = decoded.decode()
            except UnicodeDecodeError:
                raise ValueError("Failed to decode JSON.")
            else:
                return json.loads(decoded)
        elif type == "IGNORE":
            # consume all the trailing data and ignore
            ignore_count = 0
            while len(reader.peek(1)) > 0:
                ignore_count += 1
                reader.read_byte()
            return "{} bytes ignored".format(ignore_count)
        elif type in self._definitions["component"]:
            decoded = self._decode_fields(reader, self._definitions["component"][type]["fields"])
            if "extensions" in self._definitions["component"][type]:
                if not decoded["id"] in self._definitions["component"][type]["extensions"]:
                    raise NotImplementedError("{}(id={}) has not yet been implemented.".format(type, decoded["id"]))
                decoded["payload"] = self._decode_fields(reader, self._definitions["component"][type]["extensions"][
                    decoded["id"]]["fields"])
            self.dump(decoded)
            return decoded
        else:
            raise NotImplementedError("{} has not yet been implemented.".format(type))

    def dump(self, decoded, hide_unknown=False):
        if "name" not in decoded:
            decoded["name"] = "unknownName"

        print("(1){}({}): {}".format(
            decoded["name"],
            decoded["id"],
            json.dumps(self.stringify(decoded["fields"], hide_unknown), indent=2) if "fields" in decoded else ""
        ))

    def stringify(self, decoded, hide_unknown=False):
        stringified = type(decoded)()
        if type(decoded) is list:
            keys = range(len(decoded))
        else:
            keys = decoded.keys()
        for key in keys:
            if hide_unknown and key[:len("unknown_")] == "unknown_":
                continue
            value = decoded[key]
            if type(value) is bytes:
                try:
                    str = value.decode()
                except UnicodeDecodeError:
                    str = value.hex()
            elif type(value) in {dict, list, OrderedDict}:
                str = self.stringify(value)
            else:
                str = value
            if type(stringified) is list:
                stringified.append(str)
            else:
                stringified[key] = str
        return stringified
