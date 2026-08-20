# -*- coding: utf-8 -*-
"""시간표 창구 확정 - 후보 창구 x 파라미터 조합을 두드려본다."""
import json
from datetime import datetime, timezone, timedelta
from urllib import request, error
from urllib.parse import urlencode

BASE = "https://cgv.co.kr/api/v1/booking/"
CO, MOV, SITE, IMAX = "A420", "30001323", "0257", "04"
KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).strftime("%Y%m%d")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")


def get(name, params):
    url = BASE + name + "?" + urlencode(params, encoding="utf-8")
    req = request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://cgv.co.kr/cnm/movieBook/movie"})
    try:
        with request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except error.HTTPError as e:
        try: return e.code, e.read().decode("utf-8", "replace")
        except Exception: return e.code, ""
    except Exception as e:
        return 0, f"{type(e).__name__}"


ENDPOINTS = ["searchSchByMov", "searchSiteScnscYmdListByMov", "searchSiteScnscYmdListBySite",
             "searchSscnsSchdExistList", "searchSscnsSchdCntList", "searchLastScnDay",
             "searchMovScnInfo", "searchScnsMngList", "searchSscnsCdList", "searchRcmdSpclfmtInfo"]

PARAMSETS = [
    ("기본", {"coCd": CO, "movNo": MOV}),
    ("극장", {"coCd": CO, "movNo": MOV, "siteNo": SITE}),
    ("극장만", {"coCd": CO, "siteNo": SITE}),
    ("날짜", {"coCd": CO, "movNo": MOV, "siteNo": SITE, "scnYmd": TODAY}),
    ("playYmd", {"coCd": CO, "movNo": MOV, "siteNo": SITE, "playYmd": TODAY}),
    ("IMAX", {"coCd": CO, "movNo": MOV, "siteNo": SITE, "div": "CUST_EXPO_MOVTYP_CD", "attrCd": IMAX}),
]

print(f"오늘={TODAY} / 영화={MOV} / 극장={SITE} / IMAX={IMAX}")
print("=" * 74)
good = []

for ep in ENDPOINTS:
    print(f"\n■ {ep}")
    for tag, p in PARAMSETS:
        st, raw = get(ep, p)
        if st == 404:
            print(f"   404  ({tag}) 창구 없음")
            break
        short = raw.replace("\n", " ")[:330]
        flag = "OK " if st == 200 else "-- "
        print(f"   {flag}{st} ({tag}) {short}")
        if st == 200 and '"data":null' not in raw and len(raw) > 60:
            good.append((ep, tag, len(raw)))

print("\n" + "=" * 74)
print("★ 내용이 들어있던 조합:")
for g in good:
    print("   ", g)
print("=" * 74)
