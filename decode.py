#!/usr/bin/python

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

class Stream(object):
    def __init__(self, d, p=0):
        self.d = d
        self.p = p
    def tell(self):
        return self.p
    def seek(self, p):
        self.p = p
    def skip(self, off):
        self.p += off
    def read(self, cnt):
        self.skip(cnt)
        return self.d[self.p-cnt:self.p]
    def align(self, n):
        self.p = (self.p + n - 1) & ~(n - 1)
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
        "float": "<f"
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

class Asset(object):
    def __init__(self, fd):
        self.s = Stream(fd.read())

        self.s.seek(0x70)
        self.off = self.s.tell()

        self.table_size, self.data_end, self.file_gen, self.data_offset = struct.unpack(">IIII", self.s.read(16))
        self.s.read(4)
        self.version = self.s.read_str()
        self.platform = struct.unpack("<I", self.s.read(4))
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
            pathId, off, size, t1, t2, unk = struct.unpack("<QIIIH2xB", self.s.read(25))
            save = self.s.tell()
            
            self.s.seek(off + self.data_offset + self.off)
            objs.append(self.defs[t1].read(self.s))

            self.s.seek(save)
        return objs

    def decode_attrtab(self):
        code, ident, attr_cnt, stab_len = struct.unpack("<I16sII", self.s.read(28))
        #print "%08x %s" % (code, ident.encode("hex"))
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
        return code, defs[0]

def load_image(fd):
    d = Asset(fd)
    tex = [i for i in d.objs if "image data" in i]
    assert len(tex) == 1
    tex = tex[0]
    data = tex["image data"]
    width, height, fmt = tex["m_Width"], tex["m_Height"], tex["m_TextureFormat"]
    if fmt == 7: # BGR565
        im = Image.frombytes("RGB", (width, height), data, "raw", "BGR;16")
    elif fmt == 13: # ABGR4444
        im = Image.frombytes("RGBA", (width, height), data, "raw", "RGBA;4B")
        r, g, b, a  = im.split()
        im = Image.merge("RGBA", (a, b, g, r))
    else:
        raise Exception("Unsupported format %d" % fmt)
    im = im.transpose(Image.FLIP_TOP_BOTTOM)
    
    return im
    
if __name__ == "__main__":
    im = load_image(open(sys.argv[1]))
    if len(sys.argv) > 2:
        im.save(sys.argv[2])
    else:
        im.show()


