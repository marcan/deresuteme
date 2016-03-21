#!/usr/bin/python
import rijndael, base64, msgpack, hashlib, random, urllib2, time
from secrets import VIEWER_ID_KEY, SID_KEY

def decrypt_cbc(s, iv, key):
    p = "".join(rijndael.decrypt(key, "".join(s[i:i+len(iv)]))
                for i in xrange(0, len(s), len(iv)))
    return "".join(chr(ord((iv+s)[i]) ^ ord(p[i])) for i in xrange(len(p)))

def encrypt_cbc(s, iv, key):
    if len(s) % 32:
        s += "\x00" * (32 - (len(s) % 32))
    out = [iv]
    for i in range(0, len(s), 32):
        blk = "".join(chr(ord(s[i+j]) ^ ord(out[-1][j])) for j in xrange(32))
        out.append(rijndael.encrypt(key, blk))
    return "".join(out[1:])

class ApiClient(object):
    BASE = "http://game.starlight-stage.jp"
    def __init__(self, user, viewer_id, udid, res_ver="10013600"):
        self.user = user
        self.viewer_id = viewer_id
        self.udid = udid
        self.sid = None
        self.res_ver = res_ver

    def lolfuscate(self, s):
        return "%04x" % len(s) + "".join(
            "%02d" % random.randrange(100) +
            chr(ord(c) + 10) + "%d" % random.randrange(10)
            for c in s) + "%032d" % random.randrange(10**32)

    def unlolfuscate(self, s):
        return "".join(chr(ord(c) - 10) for c in s[6::4][:int(s[:4], 16)])

    def call(self, path, args):
        vid_iv = "%032d" % random.randrange(10**32)
        args["viewer_id"] = vid_iv + base64.b64encode(
            encrypt_cbc(str(self.viewer_id), vid_iv,
                        VIEWER_ID_KEY))
        plain = base64.b64encode(msgpack.packb(args))
        # I don't even
        key = base64.b64encode("".join("%x" % random.randrange(65536) for i in xrange(32)))[:32]
        msg_iv = self.udid.replace("-","")
        body = base64.b64encode(encrypt_cbc(plain, msg_iv, key) + key)
        sid = self.sid if self.sid else str(self.viewer_id) + self.udid
        headers = {
            "PARAM": hashlib.sha1(self.udid + str(self.viewer_id) + path + plain).hexdigest(),
            "KEYCHAIN": "",
            "USER_ID": self.lolfuscate(str(self.user)),
            "CARRIER": "google",
            "UDID": self.lolfuscate(self.udid),
            "APP_VER": "9.9.9",
            "RES_VER": str(self.res_ver),
            "IP_ADDRESS": "127.0.0.1",
            "DEVICE_NAME": "Nexus 42",
            "X-Unity-Version": "5.1.2f1",
            "SID": hashlib.md5(sid + SID_KEY).hexdigest(),
            "GRAPHICS_DEVICE_NAME": "3dfx Voodoo2 (TM)",
            "DEVICE_ID": hashlib.md5("Totally a real Android").hexdigest(),
            "PLATFORM_OS_VERSION": "Android OS 13.3.7 / API-42 (XYZZ1Y/74726f6c6c)",
            "DEVICE": "2",
            "Content-Type": "application/x-www-form-urlencoded", # lies
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 13.3.7; Nexus 42 Build/XYZZ1Y)",
        }
        req = urllib2.Request(self.BASE + path, body, headers)
        reply = base64.b64decode(urllib2.urlopen(req).read())
        plain = decrypt_cbc(reply[:-32], msg_iv, reply[-32:]).split("\0")[0]
        msg = msgpack.unpackb(base64.b64decode(plain))
        try:
            self.sid = msg["data_headers"]["sid"]
        except:
            pass
        return msg

if __name__ == "__main__":
    from account import user_id, viewer_id, udid
    client = ApiClient(user_id, viewer_id, udid)
    args = {
        "campaign_data": "",
        "campaign_user": 1337,
        "campaign_sign": hashlib.md5("All your APIs are belong to us").hexdigest(),
        "app_type": 0,
    }
    print client.call("/load/check", args)
    print client.call("/profile/get_profile", {"friend_id": int(sys.argv[1])})