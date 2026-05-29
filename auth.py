# -*- coding: utf-8 -*-
"""비밀번호 인증 모듈 — Streamlit Cloud secrets 사용"""
import streamlit as st
import hmac


def check_password():
    """비밀번호 입력 게이트. True 반환 시 통과."""

    def password_entered():
        if hmac.compare_digest(
            st.session_state.get("password", ""),
            st.secrets.get("app_password", ""),
        ):
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    st.markdown(
        """
        <style>
        .stApp { background-color: #0A141F; }
        h1, h2, h3 { color: #FFFFFF; }
        .login-box {
            max-width: 420px; margin: 80px auto; padding: 32px;
            background: #15202C; border-radius: 12px;
            border: 1px solid #2A3B4D;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.container():
        st.markdown('<div class="login-box">', unsafe_allow_html=True)
        st.markdown("### 🔒 AI 재고 자동 재배치")
        st.caption("E-Land 패션 BG · SPAO PoC · 내부 자료")
        st.text_input(
            "비밀번호",
            type="password",
            on_change=password_entered,
            key="password",
            placeholder="비밀번호를 입력하세요",
        )
        if "password_correct" in st.session_state and not st.session_state["password_correct"]:
            st.error("비밀번호가 올바르지 않습니다.")
        st.markdown("</div>", unsafe_allow_html=True)

    return False
