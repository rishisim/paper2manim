def get_css_toggle():
    return """
    <style>
    /* Hide code expander when toggle is OFF */
    .stApp:has(#css-toggle:not(:checked)) div[data-testid="stElementContainer"]:has(.code-marker) + div[data-testid="stElementContainer"] {
        display: none !important;
    }

    /* Hide skeleton when toggle is ON */
    .stApp:has(#css-toggle:checked) div[data-testid="stElementContainer"]:has(.skeleton-marker) {
        display: none !important;
    }

    /* The toggle switch UI */
    .switch-wrapper {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 15px;
        font-family: sans-serif;
        font-size: 14px;
        color: #ddd;
    }
    .switch {
      position: relative;
      display: inline-block;
      width: 36px;
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
      background-color: #555;
      transition: .4s;
      border-radius: 20px;
    }
    .slider:before {
      position: absolute;
      content: "";
      height: 14px;
      width: 14px;
      left: 3px;
      bottom: 3px;
      background-color: white;
      transition: .4s;
      border-radius: 50%;
    }
    input:checked + .slider {
      background-color: #FF4B4B;
    }
    input:checked + .slider:before {
      transform: translateX(16px);
    }
    </style>
    <div class="switch-wrapper">
        <label class="switch">
          <input type="checkbox" id="css-toggle" checked>
          <span class="slider"></span>
        </label>
        <span>Show real-time code changes</span>
    </div>
    """
