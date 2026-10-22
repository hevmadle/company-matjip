"""회사 맛집 추천 사이트 (Streamlit).

실행: streamlit run app.py
"""
from datetime import date

import pandas as pd
import streamlit as st

import recommend as rc

st.set_page_config(page_title="여의도 회사 맛집", page_icon="🍚", layout="wide")
st.title("🍚 여의도 회사 맛집 추천")
st.caption("여의도역 인근 회사 반경 1km 식당 · 식당 정보: 카카오·구글(실제) · 동료 리뷰: 직원 입력(예시)")

tab_rec, tab_write = st.tabs(["추천 받기", "리뷰 쓰기"])
restaurants = rc.load_restaurants()
menu_options = rc.menu_options(restaurants)

# ---------------- 추천 받기 ----------------
with tab_rec:
    c1, c2, c3 = st.columns(3)
    meal_time = c1.radio("1단계 · 언제?", ["점심", "저녁"], horizontal=True)
    purpose = c2.selectbox("2단계 · 어떤 자리?", rc.PURPOSES[meal_time])
    menus = c3.multiselect("3단계 · 메뉴 (비우면 전체)", menu_options, placeholder="전체 메뉴")

    c4, c5, c6 = st.columns(3)
    max_walk = c4.slider("걸어서 최대 몇 분?", 1, 20, 10 if meal_time == "점심" else 15)
    budget_text = c5.selectbox("1인 예산", ["상관없음", "1만 원", "2만 원", "3만 원", "5만 원", "10만 원"])
    budget = None if budget_text == "상관없음" else int(budget_text.split("만")[0]) * 10000
    only_confirmed = c6.checkbox(f"'{purpose}' 근거가 있는 곳만", value=False,
                                 disabled=purpose == "편한 외식",
                                 help="끄면 정보가 없는 식당도 보여 줘요. 정보가 없다고 안 맞는 건 아니에요.")

    result, notes, total = rc.recommend(meal_time, purpose, menus, max_walk, budget, only_confirmed)
    for note in notes:
        st.info(note)
    if not result.empty:
        st.write(f"조건에 맞는 **{total}곳** 중 상위 {len(result)}곳")
        # 화면이 다시 그려질 때마다 기록하지 않고, 조건이 바뀌었을 때만 1번 기록한다
        shown_key = (meal_time, purpose, tuple(menus), max_walk, budget, only_confirmed)
        if st.session_state.get("last_logged") != shown_key:
            rc.log_impressions(result, meal_time, purpose)
            st.session_state["last_logged"] = shown_key

    reviews = rc.load_reviews()
    for rank, (_, row) in enumerate(result.iterrows(), start=1):
        with st.container(border=True):
            left, right = st.columns([3, 1])
            left.markdown(f"### {rank}. {row['name']}")
            left.write(f"{row['menu_category']} · 걸어서 {row['walk_min']}분 · "
                       f"가격대 {row['price_level'] if pd.notna(row['price_level']) else '정보 없음'}")
            right.metric("추천 점수 (별점+가산점)", f"{row['final']:.2f}")
            for line in rc.explain(row):
                left.write("• " + line)
            if row["review_keywords"] != "모름":
                left.caption(f"구글 리뷰 키워드(참고): {row['review_keywords']}")
            mine = reviews[reviews["restaurant_id"] == row["restaurant_id"]]
            for _, r in mine.iterrows():
                left.caption(f"💬 {r['meal_time']}·{r['purpose']} ★{r['rating']} \"{r['comment']}\" ({r['data_type']})")
            left.markdown(f"[카카오맵에서 보기]({row['place_url']})")

# ---------------- 리뷰 쓰기 ----------------
with tab_write:
    st.subheader("다녀온 식당 리뷰 남기기")
    names = restaurants.sort_values("name")
    pick = st.selectbox("식당", names["restaurant_id"],
                        format_func=lambda rid: names.set_index("restaurant_id").loc[rid, "name"])
    with st.form("review_form", clear_on_submit=True):
        w1, w2 = st.columns(2)
        w_meal = w1.radio("언제 갔나요?", ["점심", "저녁"], horizontal=True)
        w_purpose = w2.selectbox("어떤 자리였나요?", sorted(set(sum(rc.PURPOSES.values(), []))))
        w_party = w1.number_input("몇 명이서?", 1, 50, 2)
        w_rating = st.slider("별점", 1, 5, 4)
        w_comment = st.text_input("한줄평")
        w_date = st.date_input("방문일", date.today())
        sent = st.form_submit_button("저장")
    if sent:
        rid = rc.add_review({
            "employee_id": "익명", "restaurant_id": pick, "meal_time": w_meal,
            "purpose": w_purpose, "party_size": int(w_party), "rating": int(w_rating),
            "comment": w_comment.strip(), "visit_date": w_date.isoformat(), "data_type": "예시",
        })
        st.success(f"저장했어요({rid}). '추천 받기' 점수에 바로 반영돼요.")
    st.write("지금까지 쌓인 동료 리뷰")
    shown = rc.load_reviews().merge(restaurants[["restaurant_id", "name"]], on="restaurant_id", how="left")
    shown = shown[["name", "meal_time", "purpose", "party_size", "rating", "comment", "visit_date", "data_type"]]
    shown.columns = ["식당", "언제", "자리", "인원", "별점", "한줄평", "방문일", "구분"]
    st.dataframe(shown.iloc[::-1], hide_index=True)
