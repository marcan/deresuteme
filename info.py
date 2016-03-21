#!/usr/bin/python
# -!- coding: utf-8 -!-
import json, base64, datetime, pytz, struct

tz = pytz.timezone("Asia/Tokyo")

def parse_ts(ts):
    dt = tz.localize(datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S"), is_dst=None)
    return int((dt - datetime.datetime(1970, 1, 1, tzinfo=pytz.utc)).total_seconds())

class ProducerInfo(object):
    DIFFICULTIES = {
        1: u"debut",
        2: u"normal",
        3: u"pro",
        4: u"master",
        #5: "master_plus",
    }
    
    
    def __init__(self, data=None):
        self.emblem_id = 1000001
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
        self.album_no = d["album_number"]
        self.creation_ts = parse_ts(d["friend_info"]["user_info"]["create_time"])
        self.last_login_ts = parse_ts(d["friend_info"]["user_info"]["last_login_time"])
        self.id = d["friend_info"]["user_info"]["viewer_id"]
        self.emblem_id = d["friend_info"]["user_info"].get("emblem_id", 1000001)
        if self.emblem_id == 0:
            self.emblem_id = 1000001

        self.leader_card = {
            u"love": int(d["friend_info"]["leader_card_info"]["love"]),
            u"level": int(d["friend_info"]["leader_card_info"]["level"]),
            u"id": int(d["friend_info"]["leader_card_info"]["card_id"]),
            u"star_rank": int(d["friend_info"]["leader_card_info"]["step"]) + 1,
            u"skill_level": int(d["friend_info"]["leader_card_info"]["skill_level"]),
            u"exp": int(d["friend_info"]["leader_card_info"]["exp"]),
        }
        
        self.cleared = {i: 0 for i in self.DIFFICULTIES.values()}
        self.full_combo = {i: 0 for i in self.DIFFICULTIES.values()}

        for i in d["user_live_difficulty_list"]:
            dt = i["difficulty_type"]
            self.cleared[self.DIFFICULTIES[dt]] = int(i["clear_number"])
            self.full_combo[self.DIFFICULTIES[dt]] = int(i["full_combo_number"])

    KEYS = ["timestamp", "id", "commu_no", "prp", "album_no", "name", "comment",
            "fan", "level", "rank", "creation_ts", "last_login_ts",
            "leader_card", "cleared", "full_combo", "emblem_id"]

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
    
