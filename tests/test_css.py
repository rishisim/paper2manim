import streamlit as st
import time

st.title("Test Pure CSS Toggle")

html_toggle = """
<style>
/* When toggle is OFF (not checked), hide elements with the class 'code-view' */
.stApp:has(#css-toggle:not(:checked)) .code-view-container {
    display: none !important;
}

/* When toggle is ON (checked), hide elements with the class 'skeleton-view' */
.stApp:has(#css-toggle:checked) .skeleton-view-container {
    display: none !important;
}

.switch {
  position: relative;
  display: inline-block;
  width: 40px;
  height: 20px;
}
.switch input { 
  opacity: 0;
  width: 0;
  height: 0;
}
.slider {
  position: absolute;
  cursor: pointer;
  top: 0; left: 0; right: 0; bottom: 0;
  background-color: #ccc;
  transition: .4s;
  border-radius: 20px;
}
.slider:before {
  position: absolute;
  content: "";
  height: 16px;
  width: 16px;
  left: 2px;
  bottom: 2px;
  background-color: white;
  transition: .4s;
  border-radius: 50%;
}
input:checked + .slider {
  background-color: #ff4b4b;
}
input:checked + .slider:before {
  transform: translateX(20px);
}
</style>
<div style="display:flex; align-items:center; gap: 10px; margin-bottom: 10px; font-family: sans-serif;">
    <label class="switch">
      <input type="checkbox" id="css-toggle" checked>
      <span class="slider"></span>
    </label>
    <span>Show real-time code changes</span>
</div>
"""

st.markdown(html_toggle, unsafe_allow_html=True)

st.markdown(
    '<div class="skeleton-view-container">SKELETON</div>', unsafe_allow_html=True
)
st.markdown('<div class="code-view-container">CODE VIEW</div>', unsafe_allow_html=True)

if st.button("Start"):
    ph1 = st.empty()
    ph2 = st.empty()
    for i in range(5):
        time.sleep(1)
        ph1.markdown(
            f'<div class="code-view-container">CODE {i}</div>', unsafe_allow_html=True
        )
        ph2.markdown(
            f'<div class="skeleton-view-container">SKEL {i}</div>',
            unsafe_allow_html=True,
        )
