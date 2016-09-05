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

import cairo, gi, base64, datetime, pytz, time, urllib, decode, StringIO, PIL
from PIL import Image
gi.require_version('Rsvg', '2.0')
from gi.repository import Rsvg
import xml.etree.ElementTree as ET

import apiclient

ns = {'svg': "http://www.w3.org/2000/svg"}
xlink = "{http://www.w3.org/1999/xlink}"
ET.register_namespace('', "http://www.w3.org/2000/svg")
ET.register_namespace('svg', "http://www.w3.org/2000/svg")
ET.register_namespace('xlink', "http://www.w3.org/1999/xlink")

def get_card(cardid, mgr, f):
    path = mgr.get("card_%d_m.unity3d" % cardid)
    im = decode.load_image(open(path))
    w, h = im.size
    im.save(f, format="PNG", compress_level=0)

def get_emblem(emblemid, mgr, f):
    path = mgr.get("emblem_%07d_l.unity3d" % emblemid)
    im = decode.load_image(open(path))
    im.save(f, format="PNG", compress_level=0)

def render_banner(data, res_mgr, card_cache=None, emblem_cache=None, base=""):
    tree = ET.parse(base + 'banner.svg')
    root = tree.getroot()
    width, height = int(root.attrib["width"]), int(root.attrib["height"])

    if data.leader_card["id"] == -2:
        card_icon = open(base + "chihiro2x.png", "r").read()
    else:
        if card_cache is None:
            output = StringIO.StringIO()
            get_card(data.leader_card["id"], res_mgr, output)
            card_icon = output.getvalue()
        else:
            card_file = card_cache(data.leader_card["id"],
                                   lambda f: get_card(data.leader_card["id"],
                                                      res_mgr, f))
            card_icon = open(card_file).read()

    if emblem_cache is None:
        output = StringIO.StringIO()
        get_emblem(data.emblem_id, res_mgr, output)
        emblem_icon = output.getvalue()
    else:
        emblem_file = emblem_cache(data.emblem_id,
                                lambda f: get_emblem(data.emblem_id,
                                                    res_mgr, f))
        emblem_icon = open(emblem_file).read()

    icon_uri = "data:image/png;base64," + base64.b64encode(card_icon)
    emblem_uri = "data:image/png;base64," + base64.b64encode(emblem_icon)

    def set_text(id, val, grp=False):
        if grp:
            e = root.findall('.//svg:g[@id="%s"]/svg:text/svg:tspan'%id, ns)
        else:
            e = root.findall('.//svg:text[@id="%s"]/svg:tspan'%id, ns)
        assert len(e) != 0
        for i in e:
            while len(i):
                del i[0]
            i.text = val

    e_icon = root.find('.//svg:image[@id="icon"]', ns)
    e_icon.set(xlink + "href", icon_uri)
    e_emblem = root.find('.//svg:image[@id="emblem"]', ns)
    e_emblem.set(xlink + "href", emblem_uri)

    set_text("level", str(data.level))
    set_text("prp", str(data.prp))
    if data.fan >= 10000:
        set_text("fan", u"%d万人" % (data.fan // 10000))
    else:
        set_text("fan", u"%d人" % data.fan)
    if data.id is None:
        root.find('.//svg:g[@id="gameid_grp"]', ns).clear()
    elif data.id == -2:
        set_text("gameid", u"エラー")
    else:
        set_text("gameid", str(data.id))
    set_text("name", data.name)
    set_text("comment", data.comment)
    for k, v in data.cleared.items():
        set_text("cl_" + k[0], str(v), grp=True)
    for k, v in data.full_combo.items():
        set_text("fc_" + k[0], str(v), grp=True)
    set_text("cardlevel", str(data.leader_card["level"]), grp=True)

    if data.emblem_ex_value:
        set_text("emblem-rank", str(data.emblem_ex_value))
    else:
        set_text("emblem-rank", "")

    for i, rank in enumerate(["f", "e", "d", "c", "b", "a", "s", "ss", "sss"]):
        if (i+1) != data.rank:
            root.find('.//svg:g[@id="rk_%s"]'%rank, ns).clear()

    img = cairo.ImageSurface(cairo.FORMAT_ARGB32, 2*width, 2*height)
    ctx = cairo.Context(img)
    handle = Rsvg.Handle().new_from_data(ET.tostring(root))
    ctx.scale(2,2)
    handle.render_cairo(ctx)
    im = Image.frombuffer("RGBA", (2*width, 2*height),
                          img.get_data(), "raw", "BGRA", 0, 1)
    return im

if __name__ == "__main__":
    import apiclient, sys, logging, resource_mgr
    from info import ProducerInfo

    logging.basicConfig()
    log = logging.getLogger("resource")
    mgr = resource_mgr.ResourceManager(10013700, "./resources/", log)

    def scale(im, fac):
        w, h = im.size
        if fac == 1:
            return im
        elif fac > 1:
            return im.resize((w/fac, h/fac), Image.BICUBIC)
        elif fac == -1:
            return im.crop((0, 0, h, h))
        elif fac == -2:
            im = im.resize((w/2, h/2), Image.BICUBIC)
            w, h = im.size
            new_im = Image.open('twitter_bg.png')
            new_w, new_h = new_im.size
            new_im.paste(im, ((new_w - w) / 2, (new_h - h) / 2), im)
            return new_im
        
    data_err = ProducerInfo.from_json(open("error.json").read())
    data_404 = ProducerInfo.from_json(open("error_404.json").read())
    data_503 = ProducerInfo.from_json(open("error_503.json").read())
    for fac in (1,2,3,4,-2,-1):
        im = render_banner(data_503, mgr)
        im = scale(im, fac)
        im.save("static/error_503_%d.png" % fac)

        im = render_banner(data_404, mgr)
        im = scale(im, fac)
        im.save("static/error_404_%d.png" % fac)

        im = render_banner(data_err, mgr)
        im = scale(im, fac)
        im.save("static/error_%d.png" % fac)

    #im = render_banner(ProducerInfo.from_json(open("card_banner.json").read()), mgr)
    ##w, h = im.size
    ##im = im.resize((w, h/2), Image.BICUBIC)
    #im.save("static/card_banner.png")
