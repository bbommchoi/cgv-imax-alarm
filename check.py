# -*- coding: utf-8 -*-
"""브라우저가 실제로 받아오는 프로그램 파일을 전부 뒤져 API 주소를 캐낸다."""
import re
from playwright.sync_api import sync_playwright

URL = "https://cgv.co.kr/cnm/movieBook/movie"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

paths, xhr = set(), set()
scripts = []

with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = b.new_context(locale="ko-KR", timezone_id="Asia/Seoul", user_agent=UA,
                        viewport={"width": 1500, "height": 1200})
    pg = ctx.new_page()

    def on_resp(r):
        rt = r.request.resource_type
        if rt == "script":
            scripts.append(r.url)
        elif rt in ("xhr", "fetch"):
            xhr.add(r.url)

    pg.on("response", on_resp)
    pg.goto(URL, wait_until="domcontentloaded", timeout=60000)
    try:
        pg.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    pg.wait_for_timeout(6000)
    for _ in range(4):
        pg.mouse.wheel(0, 1500); pg.wait_for_timeout(600)

    uniq = list(dict.fromkeys(scripts))
    print(f"[스크립트] {len(uniq)}개 받아옴")

    for u in uniq:
        try:
            body = ctx.request.get(u, timeout=20000).text()
        except Exception:
            continue
        paths |= set(re.findall(r"[\"'`](/api/v\d/[A-Za-z0-9/_.\-]{3,90})", body))
        paths |= set(re.findall(r"[\"'`](/cnm/[a-z]+/[A-Za-z0-9]{4,60})", body))
    b.close()

print("=" * 72)
print(f"[페이지가 실제 호출한 XHR] {len(xhr)}개")
for u in sorted(xhr):
    print("   ", u)

print("=" * 72)
KEY = ("atkt", "schd", "sched", "scns", "time", "ymd", "play", "book", "site", "screen", "movi", "seat")
hot = sorted(x for x in paths if any(k in x.lower() for k in KEY))
rest = sorted(x for x in paths if x not in hot)

print(f"\n★ 예매/시간표 관련 후보 ({len(hot)}개)")
for x in hot:
    print("   ", x)
print(f"\n(그 외 {len(rest)}개 중 앞 60개)")
for x in rest[:60]:
    print("   ", x)
print("\n" + "=" * 72)
print("끝. 위 내용 캡처해서 보내주세요.")
