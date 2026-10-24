"""Namespace LBAF layout and the shared JSON representation."""

import json
import unittest

from ossd import info


class InfoTest(unittest.TestCase):
    def namespace(self, index=0, metadata=0, lbads=9):
        data = bytearray(4096)
        data[:8] = (123).to_bytes(8, "little")
        data[26] = index
        off = 128 + 4 * index
        data[off : off + 2] = metadata.to_bytes(2, "little")
        data[off + 2] = lbads
        return data

    def test_lbads_is_selected_format_byte2_not_metadata(self):
        fields = {
            f["name"]: f["value"]
            for f in info.decode("namespace", self.namespace(index=2, metadata=16, lbads=12), 7)
        }
        self.assertEqual(fields["NSID"], 7)
        self.assertEqual(fields["LBA size"], 4096)
        self.assertEqual(fields["Capacity (B)"], 123 * 4096)

    def test_no_fixed_512_fallback_or_arbitrary_exponent_range(self):
        fields = {f["name"]: f["value"] for f in info.decode("namespace", self.namespace(lbads=17))}
        self.assertEqual(fields["LBA size"], 1 << 17)

    def test_json_render_uses_as_dict(self):
        result = info.ReadResult(
            "namespace",
            7,
            bytes(64),
            bytes(4096),
            fields=info.decode("namespace", self.namespace(), 7),
        )
        self.assertEqual(json.loads(info.render(result, "json")), info.as_dict(result))
