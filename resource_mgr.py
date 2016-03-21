import urllib2, hashlib, sys, os, os.path, struct, lz4, sqlite3, random, logging

def unlz4(path):
    fd = open(path)
    magic, uncomp, comp, unk = struct.unpack("<IIII", fd.read(16))
    d = lz4.loads(struct.pack("<I", uncomp) + fd.read())
    assert len(d) == uncomp
    return d

class ResourceError(Exception):
    pass

class ResourceManager(object):
    URLBASE = "http://storage.game.starlight-stage.jp/"

    def __init__(self, res_ver, cache_dir, logger):
        self.res_ver = res_ver
        self.cache_dir = cache_dir
        self.logger = logger
        self.platform = "Android"
        self.alvl = "High"
        self.slvl = "High"

    def _makedirs(self, path):
        dir, name = os.path.split(path)
        if not os.path.exists(dir):
            os.makedirs(dir)
    
    def _writefile(self, dest, data):
        self._makedirs(dest)
        tmp = dest + ".%08x" % random.randrange(2**64)
        with open(tmp, "w") as fd:
            fd.write(data)
        os.rename(tmp, dest)

    def fetch(self, path, md5=None):
        dest = self.cache_dir + "/storage/" + path
        if os.path.exists(dest):
            return dest

        url = self.URLBASE + path
        self.logger.info("Fetch: %s -> %s", url, dest)
        response = urllib2.urlopen(url)
        data = response.read()
        if md5 is not None:
            if hashlib.md5(data).hexdigest() != md5:
                raise ResourceError("MD5 digest mismatch for %s" % path)
        self._writefile(dest, data)
        return dest

    def fetch_lz4(self, path, md5=None):
        dest = self.cache_dir + "/unlz4/" + path
        if os.path.exists(dest):
            return dest

        src = self.fetch(path, md5)
        self.logger.info("unLZ4: %s -> %s", src, dest)

        data = unlz4(src)
        self._writefile(dest, data)
        return dest
        
    def load_manifest(self):
        base = "dl/%s/" % self.res_ver

        for line in open(self.fetch(base + "manifests/all_dbmanifest")):
            manifest_name, md5, plat, alvl, slvl = line.replace("\n","").split(",")
            if plat == self.platform and alvl == self.alvl and slvl == self.slvl:
                break
        else:
            raise ResourceError("Could not find suitable manifest\n")
        
        manifest_path = self.fetch_lz4(base + "manifests/%s" % manifest_name)
        con = sqlite3.connect(manifest_path)
        con.row_factory = sqlite3.Row
        return con

    def get_asset_dl_path(self, manifest_entry):
        name = manifest_entry["name"]
        md5 = manifest_entry["hash"]

        if name.endswith(".unity3d"):
            path = "dl/resources/%s/AssetBundles/%s/%s" % (self.alvl, self.platform, md5)
        elif name.endswith(".mp4") or name.endswith(".ogg"):
            # FIXME: movie quality (unused thus far?)
            path = "dl/resources/%s/Movie/%s/%s" % (self.slvl, self.platform, md5)
        elif name.endswith(".acb") or name.endswith(".awb"):
            n_dir, _ = os.path.split(name)
            path = "dl/resources/%s/Sound/Common/%s/%s" % (self.slvl, n_dir, md5)
        elif name.endswith(".mdb") or name.endswith(".bdb"):
            path = "dl/resources/Generic/%s" % md5
        else:
            raise ResourceException("Unknown asset type: %s" % name)
        
        return path
        

    def get(self, name):
        con = self.load_manifest()
        cur = con.cursor()

        cur.execute("SELECT * FROM manifests WHERE name = ?", (name,))
        row = cur.fetchone()
        if row is None:
            raise ResourceError("Resource %s not found in manifest", name)

        unlz4 = bool(row["attr"] & 1)
        if row["attr"] & ~1:
            raise ResourceError("Unknown attributes: 0x%x" % row["attr"])

        path = self.get_asset_dl_path(row)
        
        if unlz4:
            return self.fetch_lz4(path)
        else:
            return self.fetch(path)

if __name__ == "__main__":
    log = logging.getLogger("resource")
    mgr = ResourceManager(sys.argv[1], ".", log)
    print mgr.get(sys.argv[2])