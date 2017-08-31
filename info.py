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

import json, base64, datetime, pytz, struct

tz = pytz.timezone("Asia/Tokyo")

def parse_ts(ts):
    dt = tz.localize(datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S"), is_dst=None)
    return int((dt - datetime.datetime(1970, 1, 1, tzinfo=pytz.utc)).total_seconds())

def parse_card(card_info, chara_list, chara_index):
    ret = {
        u"love": int(card_info["love"]),
        u"level": int(card_info["level"]),
        u"id": int(card_info["card_id"]),
        u"star_rank": int(card_info["step"]) + 1,
        u"skill_level": int(card_info["skill_level"]),
        u"exp": int(card_info["exp"]),
    }
    if chara_list and chara_index in chara_list:
        chara_info = chara_list[chara_index]
        ret[u"character"] = {
            "id": chara_info["chara_id"],
            "vocal_boost": chara_info["param_1"],
            "dance_boost": chara_info["param_2"],
            "visual_boost": chara_info["param_3"],
            "life_boost": chara_info["param_4"],
        }
    else:
        ret[u"character"] = None
    return ret

class ProducerInfo(object):
    DIFFICULTIES = {
        1: u"debut",
        2: u"normal",
        3: u"pro",
        4: u"master",
        5: u"master_plus",
    }

    def __init__(self, data=None):
        self.emblem_id = 1000001
        self.emblem_ex_value = None
        self.support_cards = None
        if data is not None:
            self.load_data(data)

    @property
    def timestamp_fmt(self):
        dt = datetime.datetime.fromtimestamp(self.timestamp, tz)
        x = dt.strftime(u"%Y年%m月%d日 %H:%M:%S".encode("utf-8"))
        return x.decode("utf-8")

    def load_data(self, data):
        self.timestamp = int(data["data_headers"]["servertime"])
        d = data["data"]
        self.name = d["friend_info"]["user_info"]["name"]
        self.comment = d["friend_info"]["user_info"]["comment"]
        self.rank = int(d["friend_info"]["user_info"]["producer_rank"])
        self.level = int(d["friend_info"]["user_info"]["level"])
        self.prp = int(d["prp"])
        self.fan = int(d["friend_info"]["user_info"]["fan"])
        self.commu_no = int(d["story_number"])
        self.album_no = int(d["album_number"])
        self.creation_ts = parse_ts(d["friend_info"]["user_info"]["create_time"])
        self.last_login_ts = parse_ts(d["friend_info"]["user_info"]["last_login_time"])
        self.id = d["friend_info"]["user_info"]["viewer_id"]
        self.emblem_id = int(d["friend_info"]["user_info"].get("emblem_id", 1000001))
        self.emblem_ex_value = int(d["friend_info"]["user_info"].get("emblem_ex_value", None))
        if self.emblem_id == 0:
            self.emblem_id = 1000001

        self.leader_card = parse_card(d["friend_info"]["leader_card_info"],
                                      d["friend_info"]["user_chara_potential"], "chara_0")
        self.support_cards = {
            "cute":    parse_card(d["friend_info"]["support_card_info"]["1"],
                                  d["friend_info"]["user_chara_potential"], "chara_1"),
            "cool":    parse_card(d["friend_info"]["support_card_info"]["2"],
                                  d["friend_info"]["user_chara_potential"], "chara_2"),
            "passion": parse_card(d["friend_info"]["support_card_info"]["3"],
                                  d["friend_info"]["user_chara_potential"], "chara_3"),
            "all":     parse_card(d["friend_info"]["support_card_info"]["4"],
                                  d["friend_info"]["user_chara_potential"], "chara_4"),
        }

        self.cleared = {i: 0 for i in self.DIFFICULTIES.values()}
        self.full_combo = {i: 0 for i in self.DIFFICULTIES.values()}

        for i in d["user_live_difficulty_list"]:
            dt = i["difficulty_type"]
            if dt not in self.DIFFICULTIES:
                continue
            self.cleared[self.DIFFICULTIES[dt]] = int(i["clear_number"])
            self.full_combo[self.DIFFICULTIES[dt]] = int(i["full_combo_number"])

    KEYS = ["timestamp", "id", "commu_no", "prp", "album_no", "name", "comment",
            "fan", "level", "rank", "creation_ts", "last_login_ts",
            "leader_card", "cleared", "full_combo", "emblem_id",
            "emblem_ex_value", "support_cards"]

    def to_json(self):
        return json.dumps({k: getattr(self, k) for k in self.KEYS})

    @staticmethod
    def from_json(j):
        self = ProducerInfo()
        v = json.loads(j)
        for k in self.KEYS:
            if k in v:
                setattr(self, k, v[k])
        if self.emblem_id == 0:
            self.emblem_id = 1000001
        return self

if __name__ == "__main__":
    import sys, pickle

    d = json.load(open(sys.argv[1]))
    print "raw:"
    print d
    
    p1 = ProducerInfo(d)
    print
    print "to_json:"
    j = p1.to_json()
    print j
    p2 = ProducerInfo.from_json(j)
    
    assert p1.__dict__ == p2.__dict__
    #print
    #print "serialize:"
    #ser = p1.serialize()
    #print ser.encode("hex")
    #print
    #p3 = ProducerInfo.unserialize(ser)
    #assert p1.__dict__ == p3.__dict__
    
    #p2 = ProducerInfo.from_json(open("error.json").read()).serialize()
    
