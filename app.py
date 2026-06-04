# -*- coding: utf-8 -*-
"""
AI 온라인 재고 자동 재배치 — 운영 대시보드 (듀얼 버전)

- 상단 토글로 버전 전환:
  · v2.3 (최신): 자동분배 제거 · 리오더 병합 · 외부창고 분리(엔진) · 검색/제외 스타일/채널 별 세부/선택 승인
  · v1.4 (이전 참고용): 반응과 자동분배 포함 원형
- 배포: 비밀번호 게이트 (환경변수 APP_PASSWORD, 기본 'spao')
"""
import os
import streamlit as st

st.set_page_config(
    page_title='REBA_재고재배치 Agent',
    page_icon='📊',
    layout='wide',
    initial_sidebar_state='collapsed',
)


# ============================================================
# 비밀번호 게이트 (회원가입 없이 비밀번호만으로 접근)
# ============================================================
def _check_password():
    expected = None
    try:
        expected = st.secrets.get('app_password') or st.secrets.get('APP_PASSWORD')
    except Exception:
        pass
    expected = expected or os.environ.get('APP_PASSWORD', 'spao')
    if st.session_state.get('auth_ok'):
        return True

    st.markdown("""
    <style>
        .stApp { background-color: #0A141F; }
        .login-box {
            max-width: 420px; margin: 80px auto; padding: 32px;
            background: #15202C; border: 1px solid #4AE3B5;
            border-radius: 12px; text-align: center;
        }
        .login-title { color: #4AE3B5; font-size: 22px; font-weight: bold; margin-bottom: 8px; }
        .login-sub { color: #FFFFFF; font-size: 13px; margin-bottom: 24px; }
    </style>
    <div class="login-box">
        <div class="login-title">🔒 REBA_재고재배치 Agent</div>
        <div class="login-sub">운영 대시보드 · 비밀번호를 입력하세요</div>
    </div>
    """, unsafe_allow_html=True)

    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        with st.form('login_form', clear_on_submit=False):
            pw = st.text_input('Password', type='password', label_visibility='collapsed',
                               placeholder='비밀번호 입력')
            submitted = st.form_submit_button('🔓 입장', use_container_width=True, type='primary')
        if submitted:
            if pw == expected:
                st.session_state['auth_ok'] = True
                st.rerun()
            else:
                st.error('비밀번호가 올바르지 않습니다.')
        st.caption('© 2026 Fashion BG · CAIO실 AX 혁신팀')
    return False


if not _check_password():
    st.stop()

st.markdown("""
<style>
    .stApp { background-color: #0A141F; }
    .stSidebar { background-color: #15202C; }
    h1, h2, h3, h4 { color: #FFFFFF; }
    .kpi-card { background: #15202C; border: 1px solid #4AE3B5; border-radius: 8px; padding: 10px 12px; text-align: center; }
    .kpi-label { color: #FFFFFF; font-size: 11px; }
    .kpi-value { color: #4AE3B5; font-size: 26px; font-weight: bold; }
    .kpi-sub   { color: #FFFFFF; font-size: 10px; }
    .title-bar { border-left: 4px solid #4AE3B5; padding-left: 12px; color: white; font-size: 22px; font-weight: bold; margin: 4px 0 12px 0; }
    .ver-badge { display:inline-block; background:#1C2836; color:#8AB4F8; border:1px solid #8AB4F8; border-radius:12px; padding:1px 10px; font-size:12px; margin-left:10px; vertical-align:middle; }
    .scenario-box { background: #1C2836; border-left: 3px solid #4AE3B5; padding: 8px 12px; border-radius: 4px; color: #FFFFFF; font-size: 12px; margin-bottom: 8px; }
    .stDataFrame { background-color: #15202C; font-size: 11px; }
    .block-container { padding-top: 3.2rem !important; padding-bottom: 0.5rem !important; max-width: 100%; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; background: transparent; }
    .stTabs [data-baseweb="tab"] { background: #15202C; border-radius: 8px 8px 0 0; padding: 10px 24px; color: #FFFFFF; font-size: 16px; font-weight: bold; }
    .stTabs [aria-selected="true"] { background: #4AE3B5 !important; color: #0A141F !important; }
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: #FFFFFF !important; }
    [data-testid="stWidgetLabel"] p, [data-testid="stWidgetLabel"] label { color: #FFFFFF !important; }
    .stCheckbox p, .stRadio p, .stMarkdown p { color: #FFFFFF !important; }
    .stSidebar p, .stSidebar label, .stSidebar [data-testid="stWidgetLabel"] p { color: #FFFFFF !important; }
</style>
""", unsafe_allow_html=True)

# ============================================================
# 버전 전환 (v2.0 최신 / v1.4 이전 참고)
# ============================================================
ver = st.radio(
    '대시보드 버전',
    ['🟢 v2.3 (최신)', '⏪ v1.4 (이전 참고용)'],
    horizontal=True,
    key='app_version',
)

if ver.startswith('🟢'):
    import app_v20
    app_v20.render()
else:
    import app_v14
    app_v14.render()
