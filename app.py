# -*- coding: utf-8 -*-
"""
AI 온라인 재고 자동 재배치 — 운영 대시보드 (듀얼 버전)
"""
import os
import streamlit as st
from pathlib import Path

st.set_page_config(
    page_title='AICA_온라인 재고관리 Agent',
    page_icon='📊',
    layout='wide',
    initial_sidebar_state='collapsed',
)


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
    .login-box { max-width: 420px; margin: 80px auto; padding: 32px; background: #15202C; border: 1px solid #4AE3B5; border-radius: 12px; text-align: center; }
    .login-title { color: #4AE3B5; font-size: 22px; font-weight: bold; margin-bottom: 8px; }
    .login-sub { color: #FFFFFF; font-size: 13px; margin-bottom: 24px; }
    </style>
    <div class="login-box">
        <div class="login-title">🔒 AICA_온라인 재고관리 Agent</div>
        <div class="login-sub">운영 대시보드 · 비밀번호를 입력하세요</div>
    </div>
    """, unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        with st.form('login_form', clear_on_submit=False):
            pw = st.text_input('Password', type='password', label_visibility='collapsed', placeholder='비밀번호 입력')
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


def _aica_download_section():
    aica_dir = Path(__file__).parent
    html_path = aica_dir / 'AICA_morning_brief.html'
    zip_path = aica_dir / 'AICA_light.zip'
    with st.sidebar:
        st.markdown("---")
        st.markdown("### 🐱 AICA 아침 브리핑")
        st.caption("매일 아침 재고 + 대시보드 바로가기")
        with st.expander("💾 다운로드 (경량 5KB)", expanded=False):
            st.markdown("**경량 버전**: HTML + .bat · Chrome 풀스크린 알람")
            if zip_path.exists():
                with open(zip_path, 'rb') as f:
                    st.download_button(label="📥 AICA 경량 ZIP", data=f.read(),
                                       file_name='AICA_light.zip',
                                       mime='application/zip', use_container_width=True)
            if html_path.exists():
                with open(html_path, 'rb') as f:
                    st.download_button(label="📄 HTML 단독", data=f.read(),
                                       file_name='AICA_morning_brief.html',
                                       mime='text/html', use_container_width=True)
            st.caption("사용법: ZIP 풀고 .bat 더블클릭 → 매일 07:00 작업 스케줄러 등록")
        with st.expander("🐾 데스크톱 펫 (80MB)", expanded=False):
            st.markdown("바탕화면 산책 + 트레이 상주 + 자동 알람")
            st.caption("사내 NAS / OneDrive / GitHub Releases 호스팅 권장")


_aica_download_section()

ver = st.radio(
    '대시보드 버전',
    ['🟢 v5.6 (최신)', '🤖 AI 1.0 ver (테스트)'],
    horizontal=True,
    key='app_version',
)

if ver.startswith('🟢'):
    import app_v20
    app_v20.render()
else:
    import app_ai10
    app_ai10.render()
