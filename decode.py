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
try:
    import astc_decomp
except ImportError:
    pass

import struct, sys

baseStrings = {
    0:b"AABB",
    5:b"AnimationClip",
    19:b"AnimationCurve",
    49:b"Array",
    55:b"Base",
    60:b"BitField",
    76:b"bool",
    81:b"char",
    86:b"ColorRGBA",
    106:b"data",
    138:b"FastPropertyName",
    155:b"first",
    161:b"float",
    167:b"Font",
    172:b"GameObject",
    183:b"Generic Mono",
    208:b"GUID",
    222:b"int",
    241:b"map",
    245:b"Matrix4x4f",
    262:b"NavMeshSettings",
    263:b"MonoBehaviour",
    277:b"MonoScript",
    299:b"m_Curve",
    349:b"m_Enabled",
    374:b"m_GameObject",
    427:b"m_Name",
    490:b"m_Script",
    519:b"m_Type",
    526:b"m_Version",
    543:b"pair",
    548:b"PPtr<Component>",
    564:b"PPtr<GameObject>",
    581:b"PPtr<Material>",
    616:b"PPtr<MonoScript>",
    633:b"PPtr<Object>",
    688:b"PPtr<Texture>",
    702:b"PPtr<Texture2D>",
    718:b"PPtr<Transform>",
    741:b"Quaternionf",
    753:b"Rectf",
    778:b"second",
    795:b"size",
    800:b"SInt16",
    814:b"int64",
    840:b"string",
    847:b"TextAsset",
    874:b"Texture2D",
    884:b"Transform",
    894:b"TypelessData",
    907:b"UInt16",
    914:b"UInt32",
    921:b"UInt64",
    928:b"UInt8",
    934:b"unsigned int",
    981:b"vector",
    988:b"Vector2f",
    997:b"Vector3f",
    1006:b"Vector4f",
}

try:
    import lz4.block
    lz4_decompress = lz4.block.decompress
except ImportError:
    import lz4
    lz4_decompress = lz4.loads

def unlz4(data, uncomp_size):
    d = lz4_decompress(data, uncomp_size)
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
        s = self.d[self.p:].split(b"\0")[0]
        self.skip(len(s)+1)
        return s


class Def(object):
    TYPEMAP = {
        b"int": "<i",
        b"int64": "<q",
        b"char": "<1s",
        b"bool": "<B",
        b"float": "<f",
        b"unsigned int": "<I",
        b"UInt64": "<Q",
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
            #print("a", self.name)
            size = self.children[0].read(s)
            #print("ss", hex(size))
            assert size < 10000000
            if self.children[1].type_name in (b"UInt8",b"char"):
                #print("s", size)
                return s.read(size)
            else:
                return [self.children[1].read(s) for i in range(size)]
        elif self.children:
            #print("o", self.name)
            v = {}
            for i in self.children:
                v[i.name] = i.read(s)
            if len(v) == 1 and self.type_name == b"string":
                return v[b"Array"]
            return v
        else:
            x = s.tell()
            s.align(min(self.size,4))
            d = s.read(self.size)
            if self.type_name in self.TYPEMAP:
                d = struct.unpack(self.TYPEMAP[self.type_name], d)[0]
                #print("p", self.name, d)
            #else:
                #print("p", self.name)
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

COMP_TYPES = {
    0: None,
    1: "LZMA",
    2: "LZ4",
    3: "LZ4HC",
    4: "LZHAM",
}

class UnityFS(object):
    def __init__(self, s, stream_ver):
        self.s = s
        #print("stream_ver:", stream_ver)
        size, hdr_comp_size, hdr_uncomp_size, flags = struct.unpack(">QIII", self.s.read(20))
        if stream_ver >= 7:
            self.s.read(15)
        #print(">", size, hdr_comp_size, hdr_uncomp_size, "0x%x"%flags)
        if (flags & 0x80) == 0x00:
            ciblock = self.s.read(hdr_comp_size)
        else:
            ptr = self.s.tell()
            self.s.seek_end(hdr_comp_size)
            ciblock = self.s.read(hdr_comp_size)
            self.s.seek(ptr)

        comp = flags & 0x3f
        #print(comp, hdr_comp_size, hdr_uncomp_size)
        #print(ciblock.hex())
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
            if stream_ver >= 7:
                cidata.read(0)
            #print("blk", busize, bcsize, bflags)
            blk = self.s.read(bcsize)
            #print(f"bflags {bflags:#x}")
            ctype = COMP_TYPES.get(bflags & 0x3f, bflags & 0x3f)
            #print("CT", ctype)
            if ctype is None:
                pass
            elif ctype in ("LZ4", "LZ4HC"):
                blk = unlz4(blk, busize)
            else:
                raise Exception(f"Compression type {COMP_TYPES.get(bflags, str(bflags))} not supported yet")
            blocks.append(blk)

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
            #open(name,"wb").write(data)

        self.name = self.files[0][0]

class Asset(object):
    def __init__(self, fd):
        data = fd.read()
        self.s = Stream(data)
        t = self.s.read_str()
        stream_ver = struct.unpack(">I", self.s.read(4))[0]
        self.unity_version = self.s.read_str()
        self.unity_revision = self.s.read_str()
        if t == b"UnityRaw":
            ur = UnityRaw(self.s, stream_ver)
            self.fs = None
            self.s = Stream(ur.data)
            #print("UnityRaw")
        elif t == b"UnityFS":
            self.fs = UnityFS(self.s, stream_ver)
            self.s = Stream(self.fs.files[0][1])
            #print("UnityFS")
        else:
            raise Exception("Unsupported resource type %r" % t)

        self.off = self.s.align_off = self.s.tell()

        self.table_size, self.data_end, self.file_gen, self.data_offset = struct.unpack(">IIII", self.s.read(16))
        if self.file_gen >= 22:
            self.table_size, hdr_size, self.data_offset, unk = struct.unpack(">QQQQ", self.s.read(32))
        else:
            self.s.read(4)
        self.version = self.s.read_str()
        self.platform = struct.unpack("<I", self.s.read(4))[0]
        self.class_ids = []
        self.defs = self.decode_defs()
        self.objs = self.decode_data()

    def decode_defs(self):
        are_defs, count = struct.unpack("<BI", self.s.read(5))
        return dict(self.decode_attrtab() for i in range(count))

    def decode_data(self):
        count = struct.unpack("<I", self.s.read(4))[0]
        objs = []
        assert count < 1024
        for i in range(count):
            self.s.align(4)
            if self.file_gen >= 22:
                dhdr = self.s.read(24)
                pathId, off, size, type_id = struct.unpack("<QQII", dhdr)
                class_id = self.class_ids[type_id]
            elif self.file_gen >= 17:
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
            code, unk, idtype = struct.unpack("<IBH", self.s.read(7))
            if idtype == 0xffff:
                ident = self.s.read(16)
            elif idtype == 0:
                ident = self.s.read(32)
            else:
                raise Exception(f"Unknown idtype {idtype:#x}")
            attr_cnt, stab_len = struct.unpack("<II", self.s.read(8))
            #print(code, unk, ident, attr_cnt, stab_len)
        else:
            hdr = self.s.read(28)
            code, ident, attr_cnt, stab_len = struct.unpack("<I16sII", hdr)
        if self.file_gen >= 21:
            attrs = self.s.read(attr_cnt*32)
        else:
            attrs = self.s.read(attr_cnt*24)
        stab = self.s.read(stab_len)
        defs = []
        assert attr_cnt < 1024
        for i in range(attr_cnt):
            if self.file_gen >= 21:
                a1, a2, level, a4, type_off, name_off, size, idx, flags, x, y = struct.unpack("<BBBBIIIIIII", attrs[i*32:i*32+32])
                #print(a1, a2, level, a4, type_off, name_off, size, idx, flags, x, y)
            else:
                a1, a2, level, a4, type_off, name_off, size, idx, flags = struct.unpack("<BBBBIIIII", attrs[i*24:i*24+24])
                #print(a1, a2, level, a4, type_off, name_off, size, idx, flags)
            if name_off & 0x80000000:
                name = baseStrings[name_off & 0x7fffffff]
            else:
                name = stab[name_off:].split(b"\0")[0]
            if type_off == 0xffffffff:
                type_name = "unk"
            elif type_off & 0x80000000:
                type_name = baseStrings[type_off & 0x7fffffff]
            else:
                type_name = stab[type_off:].split(b"\0")[0]
            d = defs
            assert level < 16
            #print(type_name)
            for i in range(level):
                #print(d)
                d = d[-1]
            if size == 0xffffffff:
                size = None
            d.append(Def(name, type_name, size, flags, array=bool(a4)))
            #print("%2x %2x %2x %20s %8x %8x %2d: %s%s" % (a1, a2, a4, type_name, size or -1, flags, idx, "  " * level, name))

        if self.file_gen >= 21:
            self.s.read(4)

        #assert len(defs) == 1
        self.class_ids.append(code)
        return code, defs[0]

def is_image(d):
    return any(b"image data" in i for i in d.objs)

def is_audio(d):
    return any("acbFiles" in i for i in d.objs)

def decode_image(d):
    texes = [i for i in d.objs if b"image data" in i]
    for tex in texes:
        data = tex[b"image data"]
        if not data and b"m_StreamData" in tex and d.fs:
            sd = tex[b"m_StreamData"]
            name = sd[b"path"].split(b"/")[-1]
            data = d.fs.files_by_name[name][sd[b"offset"]:][:sd[b"size"]]
            #print("Streamed")
        if not data:
            continue
        width, height, fmt = tex[b"m_Width"], tex[b"m_Height"], tex[b"m_TextureFormat"]
        if fmt == 7: # BGR565
            im = Image.frombytes("RGB", (width, height), data, "raw", "BGR;16")
        elif fmt == 13: # ABGR4444
            im = Image.frombytes("RGBA", (width, height), data, "raw", "RGBA;4B")
            r, g, b, a  = im.split()
            im = Image.merge("RGBA", (a, b, g, r))
        elif fmt == 50: # ASTC_RGB_6x6
            im = Image.frombytes("RGBA", (width, height), data, "astc", (6, 6))
        else:
            continue
        im = im.transpose(Image.FLIP_TOP_BOTTOM)
        return im
    else:
        raise Exception("No supported image formats")

def load_image(fd):
    a = Asset(fd)
    return decode_image(a)

if __name__ == "__main__":
    a = Asset(open(sys.argv[1], "rb"))
    if is_image(a):
        im = decode_image(a)
        if len(sys.argv) > 2:
            im.save(sys.argv[2])
        else:
            im.show()
    else:
        for obj in a.objs:
            name = obj.get(b"m_Name", None)
            data = obj.get(b"m_Script", None)
            if name and data and isinstance(data, bytes):
                print(name)
                open(name,"wb").write(data)


