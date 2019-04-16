#!/usr/bin/python
# -!- coding: utf-8 -!-
#
# Copyright 2016 Hector Martin <marcan@marcan.st>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from PIL import Image
import struct, sys

baseStrings = {
    0:"AABB",
    5:"AnimationClip",
    19:"AnimationCurve",
    49:"Array",
    55:"Base",
    60:"BitField",
    76:"bool",
    81:"char",
    86:"ColorRGBA",
    106:"data",
    138:"FastPropertyName",
    155:"first",
    161:"float",
    167:"Font",
    172:"GameObject",
    183:"Generic Mono",
    208:"GUID",
    222:"int",
    241:"map",
    245:"Matrix4x4f",
    262:"NavMeshSettings",
    263:"MonoBehaviour",
    277:"MonoScript",
    299:"m_Curve",
    349:"m_Enabled",
    374:"m_GameObject",
    427:"m_Name",
    490:"m_Script",
    519:"m_Type",
    526:"m_Version",
    543:"pair",
    548:"PPtr<Component>",
    564:"PPtr<GameObject>",
    581:"PPtr<Material>",
    616:"PPtr<MonoScript>",
    633:"PPtr<Object>",
    688:"PPtr<Texture>",
    702:"PPtr<Texture2D>",
    718:"PPtr<Transform>",
    741:"Quaternionf",
    753:"Rectf",
    778:"second",
    795:"size",
    800:"SInt16",
    814:"int64",
    840:"string",
    874:"Texture2D",
    884:"Transform",
    894:"TypelessData",
    907:"UInt16",
    928:"UInt8",
    934:"unsigned int",
    981:"vector",
    988:"Vector2f",
    997:"Vector3f",
    1006:"Vector4f",
}

try:
    import lz4.block
    lz4_decompress = lz4.block.decompress
except ImportError:
    import lz4
    lz4_decompress = lz4.loads

def unlz4(data, uncomp_size):
    d = lz4_decompress(struct.pack("<I", uncomp_size) + data)
    assert len(d) == uncomp_size
    return d

class Stream(object):
    def __init__(self, d, p=0):
        self.d = d
        self.p = p
        self.align_off = 0
    def tell(self):
        return self.p
    def seek(self, p):
        self.p = p
    def seek_end(self, p):
        self.p = len(self.d) - p
    def skip(self, off):
        self.p += off
    def read(self, cnt=None):
        if cnt is None:
            cnt = len(self.d) - self.p
        self.skip(cnt)
        return self.d[self.p-cnt:self.p]
    def align(self, n):
        self.p = ((self.p - self.align_off + n - 1) & ~(n - 1)) + self.align_off
    def read_str(self):
        s = self.d[self.p:].split("\0")[0]
        self.skip(len(s)+1)
        return s


class Def(object):
    TYPEMAP = {
        "int": "<i",
        "int64": "<q",
        "char": "<1s",
        "bool": "<B",
        "float": "<f",
        "unsigned int": "<I",
    }
    def __init__(self, name, type_name, size, flags, array=False):
        self.children = []
        self.name = name
        self.type_name = type_name
        self.size = size
        self.flags = flags
        self.array = array
    
    def read(self, s):
        if self.array:
            #print "a", self.name
            size = self.children[0].read(s)
            assert size < 10000000
            if self.children[1].type_name in ("UInt8","char"):
                #print "s", size
                return s.read(size)
            else:
                return [self.children[1].read(s) for i in xrange(size)]
        elif self.children:
            #print "o", self.name
            v = {}
            for i in self.children:
                v[i.name] = i.read(s)
            if len(v) == 1 and self.type_name == "string":
                return v["Array"]
            return v
        else:
            x = s.tell()
            s.align(min(self.size,4))
            d = s.read(self.size)
            if self.type_name in self.TYPEMAP:
                d = struct.unpack(self.TYPEMAP[self.type_name], d)[0]
            #print hex(x), self.name, self.type_name, repr(d)
            return d

    def __getitem__(self, i):
        return self.children[i]

    def append(self, d):
        self.children.append(d)

class UnityRaw(object):
    def __init__(self, s, stream_ver):
        self.s = s
        size, hdr_size, count1, count2 = struct.unpack(">IIII", self.s.read(16))
        ptr = hdr_size
        self.s.read(count2 * 8)
        if stream_ver >= 2:
            self.s.read(4)
        if stream_ver >= 3:
            data_hdr_size = struct.unpack(">I", self.s.read(4))[0]
            ptr += data_hdr_size
        self.s.seek(ptr)
        self.data = self.s.read()

class UnityFS(object):
    def __init__(self, s, stream_ver):
        self.s = s
        size, hdr_comp_size, hdr_uncomp_size, flags = struct.unpack(">QIII", self.s.read(20))
        if (flags & 0x80) == 0x00:
            ciblock = self.s.read(hdr_comp_size)
        else:
            ptr = self.s.tell()
            self.s.seek_end(hdr_comp_size)
            ciblock = self.s.read(hdr_comp_size)
            self.s.seek(ptr)

        comp = flags & 0x3f
        if comp == 0:
            pass
        elif comp in (2, 3):
            ciblock = unlz4(ciblock, hdr_uncomp_size)
        else:
            raise Exception("Unsupported compression format %d" % comp)
        cidata = Stream(ciblock)
        guid = cidata.read(16)
        num_blocks = struct.unpack(">I", cidata.read(4))[0]
        blocks = []
        for i in range(num_blocks):
            busize, bcsize, bflags = struct.unpack(">IIH", cidata.read(10))
            if busize != bcsize:
                raise Exception("Compressed blocks not supported yet")
            blocks.append(self.s.read(busize))

        self.blockdata = b"".join(blocks)

        num_nodes = struct.unpack(">I", cidata.read(4))[0]
        self.files = []
        self.files_by_name = {}
        p = 0
        for i in range(num_nodes):
            ofs, size, status = struct.unpack(">QQI", cidata.read(20))
            name = cidata.read_str()
            #print(ofs, size, status, name)
            data = self.blockdata[p+ofs:p+ofs+size]
            self.files.append((name, data))
            self.files_by_name[name] = data

        self.name = self.files[0][0]

class Asset(object):
    def __init__(self, fd):
        self.s = Stream(fd.read())
        t = self.s.read_str()
        stream_ver = struct.unpack(">I", self.s.read(4))[0]
        self.unity_version = self.s.read_str()
        self.unity_revision = self.s.read_str()
        if t == "UnityRaw":
            ur = UnityRaw(self.s, stream_ver)
            self.fs = None
            self.s = Stream(ur.data)
            #print("UnityRaw")
        elif t == "UnityFS":
            self.fs = UnityFS(self.s, stream_ver)
            self.s = Stream(self.fs.files[0][1])
            #print("UnityFS")
        else:
            raise Exception("Unsupported resource type %r" % t)

        self.off = self.s.align_off = self.s.tell()

        self.table_size, self.data_end, self.file_gen, self.data_offset = struct.unpack(">IIII", self.s.read(16))
        self.s.read(4)
        self.version = self.s.read_str()
        self.platform = struct.unpack("<I", self.s.read(4))[0]
        self.class_ids = []
        self.defs = self.decode_defs()
        self.objs = self.decode_data()

    def decode_defs(self):
        are_defs, count = struct.unpack("<BI", self.s.read(5))
        return dict(self.decode_attrtab() for i in xrange(count))

    def decode_data(self):
        count = struct.unpack("<I", self.s.read(4))[0]
        objs = []
        assert count < 1024
        for i in xrange(count):
            self.s.align(4)
            if self.file_gen >= 17:
                dhdr = self.s.read(20)
                pathId, off, size, type_id = struct.unpack("<QIII", dhdr)
                class_id = self.class_ids[type_id]
            else:
                dhdr = self.s.read(25)
                pathId, off, size, type_id, class_id, unk = struct.unpack("<QIIIH2xB", dhdr)
            save = self.s.tell()
            self.s.seek(off + self.data_offset + self.off)

            objs.append(self.defs[class_id].read(self.s))

            self.s.seek(save)
        return objs

    def decode_attrtab(self):
        if self.file_gen >= 17:
            hdr = self.s.read(31)
            code, unk, ident, attr_cnt, stab_len = struct.unpack("<I3s16sII", hdr)
        else:
            hdr = self.s.read(28)
            code, ident, attr_cnt, stab_len = struct.unpack("<I16sII", hdr)
        attrs = self.s.read(attr_cnt*24)
        stab = self.s.read(stab_len)

        defs = []
        assert attr_cnt < 1024
        for i in xrange(attr_cnt):
            a1, a2, level, a4, type_off, name_off, size, idx, flags = struct.unpack("<BBBBIIIII", attrs[i*24:i*24+24])
            if name_off & 0x80000000:
                name = baseStrings[name_off & 0x7fffffff]
            else:
                name = stab[name_off:].split("\0")[0]
            if type_off & 0x80000000:
                type_name = baseStrings[type_off & 0x7fffffff]
            else:
                type_name = stab[type_off:].split("\0")[0]
            d = defs
            assert level < 16
            for i in range(level):
                d = d[-1]
            if size == 0xffffffff:
                size = None
            d.append(Def(name, type_name, size, flags, array=bool(a4)))
            #print "%2x %2x %2x %20s %8x %8x %2d: %s%s" % (a1, a2, a4, type_name, size or -1, flags, idx, "  " * level, name)

        assert len(defs) == 1
        self.class_ids.append(code)
        return code, defs[0]

def load_image(fd):
    d = Asset(fd)
    texes = [i for i in d.objs if "image data" in i]
    for tex in texes:
        data = tex["image data"]
        if not data and "m_StreamData" in tex and d.fs:
            sd = tex["m_StreamData"]
            name = sd["path"].split("/")[-1]
            data = d.fs.files_by_name[name][sd["offset"]:][:sd["size"]]
            #print("Streamed")
        if not data:
            continue
        width, height, fmt = tex["m_Width"], tex["m_Height"], tex["m_TextureFormat"]
        if fmt == 7: # BGR565
            im = Image.frombytes("RGB", (width, height), data, "raw", "BGR;16")
        elif fmt == 13: # ABGR4444
            im = Image.frombytes("RGBA", (width, height), data, "raw", "RGBA;4B")
            r, g, b, a  = im.split()
            im = Image.merge("RGBA", (a, b, g, r))
        else:
            continue
        im = im.transpose(Image.FLIP_TOP_BOTTOM)
        return im
    else:
        raise Exception("No supported image formats")

if __name__ == "__main__":
    im = load_image(open(sys.argv[1]))
    if len(sys.argv) > 2:
        im.save(sys.argv[2])
    else:
        im.show()


