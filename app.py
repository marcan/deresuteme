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

import os.path, os, random, threading, time, json, logging, base64, hashlib, io, struct
from keys import BLOB_KEY
from PIL import Image
from Crypto.Cipher import AES

import account, render, apiclient, resource_mgr, decode
from info import ProducerInfo

from flask import Flask, send_file, request, make_response, abort, render_template, redirect
app = Flask(__name__)

if __name__ == "__main__":
    app.config['DEBUG'] = True

BASE = os.path.dirname(os.path.abspath(__file__)) + "/"

CARD_CACHE_DIR = BASE + "data/cards/"
EMBLEM_CACHE_DIR = BASE + "data/emblems/"
BANNER_CACHE_DIR = BASE + "data/banners/"
INFO_CACHE_DIR = BASE + "data/info/"
SNAPSHOT_DIR = BASE + "data/snap/"
RESOURCES_DIR = BASE + "data/resources/"

THROTTLE = 2
RES_POLL = 600

LOG_FILE = BASE + "log/info.log"

DEF_MAX_AGE = 300

g_client = apiclient.ApiClient(account.user_id, account.viewer_id, account.udid)
g_lock = threading.Lock()
g_last_fetch = 0
g_last_check = 0
g_resmgr = resource_mgr.ResourceManager(g_client.res_ver, RESOURCES_DIR, app.logger)

class RequestFormatter(logging.Formatter):
    def format(self, record):
        s = logging.Formatter.format(self, record)
        try:
            return '[%s] [%d] [%s] [%s %s] ' % (self.formatTime(record), account.index, request.remote_addr, request.method, request.path) + s
        except:
            return '[%s] [%d] [SYS] ' % (self.formatTime(record), account.index) + s

if not app.debug:
    import socket, pwd
    from logging.handlers import SMTPHandler, WatchedFileHandler
    username = pwd.getpwuid(os.getuid()).pw_name
    mail_handler = SMTPHandler('127.0.0.1',
                                '%s@%s' % (username, socket.getfqdn()),
                                'postmaster', 'deresute.me error')
    mail_handler.setLevel(logging.ERROR)
    app.logger.addHandler(mail_handler)

    handler = WatchedFileHandler(os.path.join(app.root_path, LOG_FILE))
    handler.setLevel(logging.INFO)
    handler.setFormatter(RequestFormatter())
    app.logger.addHandler(handler)

    app.logger.setLevel(logging.INFO)
    app.logger.warning('Starting...')

def get_cache(cachedir, name, fetch, max_age=None):
    path = cachedir + name
    if os.path.exists(path):
        age = max(0, time.time() - os.stat(path).st_mtime)
        if max_age is None or age < max_age:
            app.logger.info("Cache hit on %s", path)
            return path, age
    tmp = path + ".%08x" % random.randrange(2**64)
    app.logger.info("Cache miss, fetching at %s", tmp)
    fetch(tmp)
    os.rename(tmp, path)
    age = min(0, time.time() - os.stat(path).st_mtime)
    return path, age

class APIError(Exception):
    def __init__(self, code):
        Exception.__init__(self, "API error %d (viewer_id: %d)" % (code, g_client.viewer_id))
        self.code = code

def do_check():
    global g_client
    args = {
        "campaign_data": "",
        "campaign_user": 1337,
        "campaign_sign": "fb9d4400538f6ca7c1bab38f274afac1",
        "app_type": 0,
    }
    check = g_client.call("/load/check", args)
    app.logger.info("Check result: %r", check)
    return check

def new_resources(res_ver):
    global g_client, g_resmgr, g_last_check
    app.logger.info("Resource update: %s -> %s", g_client.res_ver, res_ver)
    g_client.res_ver = res_ver
    do_check()
    g_resmgr = resource_mgr.ResourceManager(g_client.res_ver, RESOURCES_DIR, app.logger)
    g_last_check = time.time()

def update_resources():
    global g_lock, g_client, g_last_fetch, g_last_check, g_resmgr

    with g_lock:
        check_age = time.time() - g_last_check
        if check_age > RES_POLL or g_resmgr is None:
            app.logger.info("Check age is %d, invoking check", check_age)
            check = do_check()
            if "required_res_ver" in check["data_headers"]:
                if check["data_headers"]["required_res_ver"] != g_client.res_ver:
                    time.sleep(1.1)
                    new_resources(check["data_headers"]["required_res_ver"])
                else:
                    app.logger.info("Spurious resource update, API call probably needs fixing")
            elif check["data_headers"]["result_code"] in (101, 208):
                g_last_check = time.time()

def load_info(user_id, dst):
    global g_lock, g_client, g_last_fetch, g_last_check, g_resmgr
    app.logger.info("Query %d", user_id)

    update_resources()

    while True:
        with g_lock:
            left = g_last_fetch + THROTTLE - time.time()
            if left > 0:
                app.logger.info("Throttling: %r sec", left)
                time.sleep(left)

            d = g_client.call("/profile/get_profile", {"friend_id": user_id})
            app.logger.info("Result: %r", d)
            g_last_fetch = time.time()
            if "required_res_ver" in d["data_headers"]:
                app.logger.info("Query failed due to stale res_ver, updating")
                time.sleep(1.1)
                new_resources(d["data_headers"]["required_res_ver"])
                continue
            break

    with open(dst, "w") as fd:
        json.dump(d, fd)

def gen_banner(data, dst, mtime=None):
    update_resources()

    def card_cache(card_id, getfunc):
        card, age = get_cache(CARD_CACHE_DIR, "%d.png" % card_id, getfunc)
        return card

    def emblem_cache(emblem_id, getfunc):
        emblem, age = get_cache(EMBLEM_CACHE_DIR, "%d.png" % emblem_id, getfunc)
        return emblem

    im = render.render_banner(data, card_cache=card_cache, emblem_cache=emblem_cache,
                              res_mgr=g_resmgr, base=BASE)
    im.save(dst, "PNG")
    if mtime is not None:
        os.utime(dst, (mtime, mtime))

def resize_banner(src, dst, size_div):
    mtime = os.stat(src).st_mtime
    im = Image.open(src)
    w, h = im.size
    im = im.resize((w//size_div, h//size_div), Image.BICUBIC)
    im.save(dst, "PNG")
    os.utime(dst, (mtime, mtime))

def crop_banner(src, dst):
    mtime = os.stat(src).st_mtime
    im = Image.open(src)
    w, h = im.size
    im = im.crop((0, 0, h, h))
    im.save(dst, "PNG")
    os.utime(dst, (mtime, mtime))

def expand_banner(src, dst):
    mtime = os.stat(src).st_mtime
    im = Image.open(src)
    w, h = im.size
    #new_h = w * 150 // 280
    #new_im = Image.new('RGBA', (w, new_h), (0, 0, 0, 0))
    new_im = Image.open(BASE + 'twitter_bg.png')
    new_w, new_h = new_im.size
    new_im.paste(im, ((new_w - w) // 2, (new_h - h) // 2), im)
    new_im.save(dst, "PNG")
    os.utime(dst, (mtime, mtime))

def get_data(user_id, max_age=DEF_MAX_AGE):
    if user_id < 100000000:
        raise APIError(1457)
    jsonf, age = get_cache(INFO_CACHE_DIR, "%d.json" % user_id,
                           lambda f: load_info(user_id, f), max_age=max_age)
    mtime = os.stat(jsonf).st_mtime
    with open(jsonf) as fd:
        data = json.load(fd)

    if data["data_headers"]["result_code"] != 1:
        raise APIError(data["data_headers"]["result_code"])
    if "data" not in data:
        raise Exception("No data returned")

    return ProducerInfo(data), mtime

def privatize(data, privacy):
    if privacy >= 1:
        data.id = None
        data.last_login_ts = None
        data.creation_ts = None
    if privacy >= 2:
        data.name = len(data.name) * "◯"
    if privacy >= 3:
        data.comment = min(16,len(data.comment)) * "◯"

def get_sized_banner(key, data, mtime, size_div, max_age=DEF_MAX_AGE):
    master, age = get_cache(BANNER_CACHE_DIR, "%s.png" % key,
                            lambda f: gen_banner(data, f, mtime),
                            max_age=max_age)
    if max_age is not None:
        cache_timeout = max_age - age
    else:
        cache_timeout = None

    if size_div == 1:
        return send_file(master, mimetype="image/png",
                         max_age=cache_timeout)
    elif size_div == -1:
        sized, age = get_cache(BANNER_CACHE_DIR, "%s_sq.png" % key,
                            lambda f: crop_banner(master, f),
                            max_age=max_age)
        return send_file(sized, mimetype="image/png", max_age=cache_timeout)
    elif size_div == -2:
        sized, age = get_cache(BANNER_CACHE_DIR, "%s_s%d.png" % (key, 2),
                            lambda f: resize_banner(master, f, 2),
                            max_age=max_age)

        sized, age = get_cache(BANNER_CACHE_DIR, "%s_tw.png" % key,
                            lambda f: expand_banner(sized, f),
                            max_age=max_age)
        return send_file(sized, mimetype="image/png", max_age=cache_timeout)

    sized, age = get_cache(BANNER_CACHE_DIR, "%s_s%d.png" % (key, size_div),
                           lambda f: resize_banner(master, f, size_div),
                           max_age=max_age)
    return send_file(sized, mimetype="image/png", max_age=cache_timeout)

sizemap = {
    "square": -1,
    "twcard": -2,
    "twitter": -2,
    "small": 4,
    "medium": 3,
    "large": 2,
    "huge": 1
}

def try_get_banner(user_id, sizename, privacy=0):
    if sizename.endswith(".png"):
        sizename = sizename[:-4]
    if sizename not in sizemap:
        abort(404)
    if len(str(user_id)) != 9:
        abort(404)
    size = sizemap[sizename]
    try:
        data, mtime = get_data(user_id)
        key = "%d_p%d" % (user_id, privacy)
        privatize(data, privacy)
        res = get_sized_banner(key, data, mtime, size)
        if data.id is None:
            user_id = 0
        if request.query_string == b"dl":
            res.headers['Content-Disposition'] = 'attachment; filename=%d_p%d_%s.png' % (user_id, privacy, sizename)
        else:
            res.headers['Content-Disposition'] = 'filename=%d_p%d_%s.png' % (user_id, privacy, sizename)
        return res
    except APIError as e:
        if e.code == 1457:
            return send_file("static/error_404_%d.png" % size, mimetype="image/png", max_age=60)
        elif e.code == 101:
            return send_file("static/error_503_%d.png" % size, mimetype="image/png", max_age=60)
        else:
            app.logger.exception("API error for %r/%r/%r" % (user_id, sizename, privacy))
            return send_file("static/error_%d.png" % size, mimetype="image/png", max_age=60)
    except Exception as e:
        app.logger.exception("Exception thrown for %r/%r/%r" % (user_id, sizename, privacy))
        return send_file("static/error_%d.png" % size, mimetype="image/png", max_age=60)

def load_snap(snap):
    try:
        snap = str(snap)
    except:
        abort(404)
    if len(str(snap)) != 16:
        abort(404)
    try:
        base64.b64decode(snap.encode("ascii"), b"-_")
    except:
        abort(404)

    jsonf, age = get_cache(SNAPSHOT_DIR, "%s.json" % snap, lambda p: abort(404))
    with open(jsonf) as fd:
        data = ProducerInfo.from_json(fd.read())
    return data

def try_get_snap(snap, sizename):
    if sizename.endswith(".png"):
        sizename = sizename[:-4]
    if sizename not in sizemap:
        abort(404)
    size = sizemap[sizename]
    data = load_snap(snap)
    key = "s_" + snap
    res = get_sized_banner(key, data, None, size, max_age=None)
    if request.query_string == "dl":
        res.headers['Content-Disposition'] = 'attachment; filename=snap_%s_%s.png' % (snap, sizename)
    return res

def try_make_snap(user_id, privacy, tweet=False):
    try:
        data, mtime = get_data(user_id, max_age=60)
        privatize(data, privacy)
        d = data.to_json().encode("ascii")
        h = base64.b64encode(hashlib.sha1(d).digest()[:12], b"-_").decode("ascii")
        def save_json(path):
            with open(path, "wb") as fd:
                fd.write(d)
        get_cache(SNAPSHOT_DIR, "%s.json" % h, save_json)
        if tweet:
            return redirect("https://twitter.com/intent/tweet?url=https://deresute.me/s/" + h)
        else:
            return redirect("/s/" + h)
    except APIError as e:
        if e.code not in (1457, 101):
            app.logger.exception("API error for %r/%r" % (user_id, privacy))
        return redirect("/%d" % user_id)
    except Exception as e:
        app.logger.exception("Exception thrown for %r/%r" % (user_id, privacy))
        return redirect("/%d" % user_id)

def decode_blob(blob):
    if len(blob) != 22:
        abort(400)
    try:
        d = base64.b64decode(blob.encode("ascii") + b"==", b"-_")
        d = AES.new(BLOB_KEY, AES.MODE_ECB).decrypt(d)
        ver, user_id, privacy, check = struct.unpack("<BIB6x4s", d)
    except:
        abort(400)
    if ver != 1:
        abort(400)
    if check != b"\x00\x00\x00\x00":
        abort(400)
    if privacy not in (1,2,3):
        abort(400)
    return user_id, privacy

@app.route("/")
def index():
    return render_template('index.html', data=None, snapshot=None)

@app.route("/<int:user_id>")
def index_user(user_id):
    if len(str(user_id)) != 9:
        abort(404)
    try:
        data, mtime = get_data(user_id)
        return render_template('index.html', data=data, snapshot=None)
    except APIError as e:
        if e.code not in (1457, 101):
            app.logger.exception("API error for %r" % user_id)
        else:
            app.logger.info("Returning generic HTML for /%r (code %d)" % (user_id, e.code))
        return index()
    except Exception as e:
        app.logger.exception("Exception thrown for %r" % user_id)
        return index()

@app.route("/snap/<snap>")
@app.route("/s/<snap>")
def index_snap(snap):
    data = load_snap(snap)
    return render_template('index.html', data=data, snapshot=snap)

@app.route("/snap/<snap>/json")
@app.route("/s/<snap>/json")
def get_snap_json(snap):
    data = load_snap(snap)
    resp = make_response(data.to_json())
    resp.mimetype = "application/json"
    return data.to_json(), 200, {"Content-Type": "application/json"}

@app.route("/snap/<snap>/<size>")
@app.route("/s/<snap>/<size>")
def get_snap(snap, size):
    return try_get_snap(snap, size)

@app.route("/<int:user_id>/json")
def get_json(user_id):
    try:
        data, mtime = get_data(user_id)
        resp = make_response(data.to_json())
        resp.mimetype = "application/json"
        return data.to_json(), 200, {"Content-Type": "application/json"}
    except APIError as e:
        data = {"api_error": e.code}
        if e.code == 1457:
            return json.dumps(data), 404, {"Content-Type": "application/json"}
        elif e.code == 101:
            return json.dumps(data), 503, {"Content-Type": "application/json"}
        else:
            app.logger.exception("API error for %r" % user_id)
            return json.dumps(data), 500, {"Content-Type": "application/json"}
    except Exception as e:
        resp = make_response(json.dumps({"error": -1}))
        app.logger.exception("Exception thrown for %r" % user_id)
        resp.mimetype = "application/json"
        return resp

@app.route("/<int:user_id>/snap", methods=['POST'])
def make_snap(user_id):
    return try_make_snap(user_id, 0)

@app.route("/<int:user_id>/tweet", methods=['POST'])
def make_snap_and_tweet(user_id):
    return try_make_snap(user_id, 0, tweet=True)

@app.route("/<int:user_id>/p<int:privacy>/snap", methods=['POST'])
def make_snap_priv(user_id, privacy):
    if privacy not in (1,2,3):
        abort(404)
    return try_make_snap(user_id, privacy)

@app.route("/<int:user_id>/p<int:privacy>/blob")
def make_blob(user_id, privacy):
    if privacy not in (1,2,3):
        abort(404)
    d = struct.pack("<BIB6s4x", 1, user_id, privacy, os.urandom(6))
    d = AES.new(BLOB_KEY, AES.MODE_ECB).encrypt(d)
    return base64.b64encode(d, b"-_")[:-2]

@app.route("/<int:user_id>/p<int:privacy>/tweet", methods=['POST'])
def make_snap_priv_and_tweet(user_id, privacy):
    if privacy not in (1,2,3):
        abort(404)
    return try_make_snap(user_id, privacy, tweet=True)

@app.route("/<int:user_id>/<size>")
def get_size(user_id, size):
    return try_get_banner(user_id, size, privacy=0)

@app.route("/<int:user_id>/p<int:privacy>/<size>")
def get_size_priv(user_id, privacy, size):
    if privacy not in (1,2,3):
        abort(404)
    return try_get_banner(user_id, size, privacy=privacy)

@app.route("/<blob>/<size>")
def get_size_blob(blob, size):
    user_id, privacy = decode_blob(blob)
    return get_size_priv(user_id, privacy, size)

@app.route("/test_500")
def get_500():
    raise Exception("Exception test")

@app.route("/res_ver")
def get_res_ver():
    update_resources()
    return g_client.res_ver

@app.route("/res/<resource>")
def get_resource(resource):
    update_resources()
    try:
        res = g_resmgr.get(resource + ".unity3d")
    except resource_mgr.ResourceError:
        abort(404)

    im = decode.load_image(open(res, "rb"))
    fd = io.BytesIO()
    im.save(fd, format="PNG")
    rs = make_response(fd.getvalue())
    rs.headers['Content-Type'] = 'image/png'
    return rs

if __name__ == "__main__":
    app.run()
