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

import base64, msgpack, hashlib, random, urllib.request, urllib.error, urllib.parse, time, json
from Crypto.Cipher import AES
from Crypto.Util import Padding

from keys import VIEWER_ID_KEY, SID_KEY

def decrypt_cbc(s, iv, key):
    aes = AES.new(key, AES.MODE_CBC, iv)
    return Padding.unpad(aes.decrypt(s), 16)

def encrypt_cbc(s, iv, key):
    aes = AES.new(key, AES.MODE_CBC, iv)
    return aes.encrypt(Padding.pad(s, 16))

def deep_decode(data):
    if isinstance(data, bytes):      return data.decode("utf-8")
    if isinstance(data, dict):       return dict(map(deep_decode, data.items()))
    if isinstance(data, tuple):      return tuple(map(deep_decode, data))
    if isinstance(data, list):       return list(map(deep_decode, data))
    return data

class ApiClient(object):
    BASE = "https://apis.game.starlight-stage.jp"
    def __init__(self, user, viewer_id, udid, res_ver="10088500"):
        self.user = user
        self.viewer_id = viewer_id
        self.udid = udid
        self.sid = None
        self.res_ver = res_ver

    def lolfuscate(self, s):
        return "%04x" % len(s) + "".join(
            "%02d" % random.randrange(100) +
            chr(ord(c) + 10) + "%d" % random.randrange(10)
            for c in s) + "%016d" % random.randrange(10**16)

    def unlolfuscate(self, s):
        return "".join(chr(ord(c) - 10) for c in s[6::4][:int(s[:4], 16)])

    def call(self, path, args):
        vid_iv = "%016d" % random.randrange(10**16)
        args["timezone"] = "09:00:00"
        args["viewer_id"] = vid_iv + base64.b64encode(
            encrypt_cbc(str(self.viewer_id).encode("ascii"),
                        vid_iv.encode("ascii"),
                        VIEWER_ID_KEY)).decode("ascii")
        plain = base64.b64encode(msgpack.packb(args))
        # I don't even
        key = base64.b64encode(b"".join(b"%x" % random.randrange(65536) for i in range(32)))[:32]
        print(repr(key))
        msg_iv = bytes.fromhex(self.udid.replace("-",""))
        body = base64.b64encode(encrypt_cbc(plain, msg_iv, key) + key)
        sid = self.sid if self.sid else (str(self.viewer_id) + self.udid).encode("ascii")
        headers = {
            "APP-VER": "15.0.0",
            "IP-ADDRESS": "1.2.3.4",
            "X-Unity-Version": "2017.4.2f2",
            "DEVICE": "2",
            "DEVICE-ID": hashlib.md5(b"Totally a real Android 2").hexdigest(),
            "GRAPHICS-DEVICE-NAME": "Adreno (TM) 512",
            "PARAM": hashlib.sha1((self.udid + str(self.viewer_id) + path + plain.decode("ascii")).encode("ascii")  ).hexdigest(),
            "PLATFORM-OS-VERSION": "Android OS 8.1.0 / API-27 (OPM7.181005.003/0000000000)",
            "UDID": self.lolfuscate(self.udid),
            "CARRIER": "google",
            "SID": hashlib.md5(sid + SID_KEY).hexdigest(),
            "RES-VER": str(self.res_ver),
            "IDFA": "",
            "KEYCHAIN": "",
            "PROCESSOR-TYPE": "ARMv7 VFPv3 NEON",
            "USER-ID": self.lolfuscate(str(self.user)),
            "DEVICE-NAME": "Nexus 4",
            "Content-Type": "application/x-www-form-urlencoded", # lies
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 8.1.0; Nexus 4 Build/XYZZ1Y)",
        }
        for i in range(3):
            try:
                req = urllib.request.Request(self.BASE + path, body, headers)
                reply = urllib.request.urlopen(req).read()
            except urllib.error.URLError as e:
                if i >= 2:
                    raise
                else:
                    continue
        reply = base64.b64decode(reply)
        plain = decrypt_cbc(reply[:-32], msg_iv, reply[-32:]).split(b"\0")[0]
        msg = msgpack.unpackb(base64.b64decode(plain), strict_map_key=False)
        try:
            self.sid = msg[b"data_headers"][b"sid"]
        except:
            pass
        return deep_decode(msg)

if __name__ == "__main__":
    import sys, pprint
    from account import user_id, viewer_id, udid
    import apiclient
    client = apiclient.ApiClient(user_id, viewer_id, udid)
    args = {
        "campaign_data": "",
        "campaign_user": 144234,
        "campaign_sign": hashlib.md5(b"All your APIs are belong to us 2").hexdigest(),
        "app_type": 0,
        "cl_log_params": {'udid': '', 'userId': '', 'viewerId': 0},
        'error_text': '',
    }
    print(client.call("/load/check", args))
    pprint.pprint(client.call("/load/index", args))
    pprint.pprint(client.call("/profile/get_profile", {"friend_id": int(sys.argv[1])}))
