import streamlit as st
import time

if "show" not in st.session_state:
    st.session_state.show = True


@st.fragment
def toggle_frag():
    st.session_state.show = st.toggle("Show", value=st.session_state.show)
    st.write(f"Toggle is {st.session_state.show}")


if st.button("Start"):
    toggle_frag()

    ph = st.empty()
    for i in range(10):
        time.sleep(1)
        if st.session_state.show:
            ph.write(f"Code {i}")
        else:
            ph.write(f"Skeleton {i}")
