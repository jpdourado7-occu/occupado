with open('app.py', encoding='utf-8') as f:
    src = f.read()

# ── 1. Add Syne back to all font import URLs ───────────────────────────────
src = src.replace(
    'family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap',
    'family=Syne:wght@700;800&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap'
)

# ── 2. Fix old Syne+DM imports in settings and map-fields ─────────────────
src = src.replace(
    'family=Syne:wght@700;800&family=DM+Sans:wght@400;500&family=DM+Mono&display=swap',
    'family=Syne:wght@700;800&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap'
)
print('Font import URLs: done')

# ── 3. Switch all logo/brand elements to Syne ─────────────────────────────
# Login + Register .brand
src = src.replace(
    ".brand{{font-family:'Plus Jakarta Sans',sans-serif;font-size:22px;font-weight:800;color:#0d1120;letter-spacing:-0.5px;margin-bottom:28px;}}",
    ".brand{{font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:#0d1120;letter-spacing:-0.5px;margin-bottom:28px;}}"
)
# VdV topbar brand
src = src.replace(
    ".tb-brand{{font-size:15px;font-weight:700;letter-spacing:-0.3px;color:#111827;font-family:'Plus Jakarta Sans',sans-serif;}}",
    ".tb-brand{{font-size:15px;font-weight:700;letter-spacing:-0.3px;color:#111827;font-family:'Syne',sans-serif;}}"
)
# Settings + map-fields topbar-logo (will be set per-page below)
print('Logo font -> Syne: done')

# ── 4. Replace DM Sans / DM Mono ──────────────────────────────────────────
src = src.replace("'DM Sans',sans-serif", "'Plus Jakarta Sans',sans-serif")
src = src.replace("'DM Mono',monospace", "'JetBrains Mono',monospace")
print('DM fonts replaced: done')

# ── 5. Redesign settings page CSS ─────────────────────────────────────────
old_settings_css = (
    "* {{ margin:0; padding:0; box-sizing:border-box; }}\n"
    "body {{ background:#ffffff; color:#0a1a0a; font-family:'Plus Jakarta Sans',sans-serif; }}\n"
    ".topbar {{ background:#008000; padding:16px 40px; display:flex; align-items:center; justify-content:space-between; }}\n"
    ".topbar-logo {{ font-family:'Plus Jakarta Sans',sans-serif; font-size:22px; font-weight:800; color:#ffffff; }}\n"
    ".topbar-hotel {{ font-family:'JetBrains Mono',monospace; font-size:12px; color:rgba(255,255,255,0.8); }}\n"
    ".topbar-right {{ display:flex; align-items:center; gap:10px; }}\n"
    ".btn-nav {{ padding:8px 18px; background:rgba(255,255,255,0.15); border:1px solid rgba(255,255,255,0.3); border-radius:8px; color:#ffffff; font-size:13px; font-weight:600; text-decoration:none; }}\n"
    ".btn-nav:hover {{ background:rgba(255,255,255,0.25); }}\n"
    ".content {{ padding:60px 40px; display:flex; align-items:center; justify-content:center; min-height:calc(100vh - 80px); }}\n"
    ".wrapper {{ width:100%; max-width:500px; text-align:center; }}\n"
    ".page-title {{ font-family:'Plus Jakarta Sans',sans-serif; font-size:36px; font-weight:800; margin-bottom:8px; }}\n"
    ".page-sub {{ font-family:'JetBrains Mono',monospace; font-size:12px; color:#4a6648; margin-bottom:40px; }}\n"
    ".card {{ background:#f5faf5; border:1px solid rgba(0,128,0,0.15); border-radius:16px; padding:40px; }}\n"
    ".card-title {{ font-family:'Plus Jakarta Sans',sans-serif; font-size:18px; font-weight:700; margin-bottom:12px; }}\n"
    ".card-sub {{ font-size:13px; color:#4a6648; margin-bottom:24px; }}\n"
    "label {{ font-size:12px; color:#4a6648; display:block; margin-bottom:8px; font-family:'JetBrains Mono',monospace; font-weight:600; text-align:left; }}\n"
    "input {{ width:100%; padding:12px 16px; background:#ffffff; border:1px solid rgba(0,128,0,0.2); border-radius:10px; font-size:14px; margin-bottom:20px; font-family:'Plus Jakarta Sans',sans-serif; }}\n"
    "input:focus {{ border-color:#008000; outline:none; }}\n"
    "button {{ padding:12px 32px; background:#008000; color:white; border:none; border-radius:10px; font-weight:600; cursor:pointer; font-size:14px; font-family:'Plus Jakarta Sans',sans-serif; }}\n"
    "button:hover {{ background:#006600; }}"
)

new_settings_css = (
    "*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box;}}\n"
    "body{{background:#f9fafb;color:#111827;font-family:'Plus Jakarta Sans',sans-serif;-webkit-font-smoothing:antialiased;}}\n"
    ".topbar{{background:#fff;border-bottom:1px solid #e5e7eb;padding:0 40px;height:56px;display:flex;align-items:center;justify-content:space-between;}}\n"
    ".topbar-logo{{font-family:'Syne',sans-serif;font-size:18px;font-weight:800;color:#111827;letter-spacing:-0.3px;}}\n"
    ".topbar-logo span{{color:#00d165;}}\n"
    ".topbar-hotel{{font-size:11px;color:#9ca3af;font-family:'JetBrains Mono',monospace;margin-top:2px;}}\n"
    ".topbar-right{{display:flex;align-items:center;gap:8px;}}\n"
    ".btn-nav{{padding:7px 16px;background:#fff;border:1px solid #e5e7eb;border-radius:8px;color:#374151;font-size:13px;font-weight:500;text-decoration:none;transition:border-color .15s;}}\n"
    ".btn-nav:hover{{border-color:#111827;color:#111827;}}\n"
    ".content{{padding:60px 40px;display:flex;align-items:center;justify-content:center;min-height:calc(100vh - 56px);}}\n"
    ".wrapper{{width:100%;max-width:480px;text-align:center;}}\n"
    ".page-title{{font-size:28px;font-weight:700;color:#111827;letter-spacing:-0.5px;margin-bottom:6px;}}\n"
    ".page-sub{{font-size:13px;color:#6b7280;margin-bottom:36px;}}\n"
    ".card{{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:36px;}}\n"
    ".card-title{{font-size:16px;font-weight:600;color:#111827;margin-bottom:8px;}}\n"
    ".card-sub{{font-size:13px;color:#6b7280;margin-bottom:24px;}}\n"
    "label{{font-size:10px;font-weight:500;color:#9ca3af;text-transform:uppercase;letter-spacing:.08em;display:block;margin-bottom:7px;text-align:left;font-family:'JetBrains Mono',monospace;}}\n"
    "input{{width:100%;padding:11px 14px;background:#fff;border:1px solid #e5e7eb;border-radius:8px;font-size:14px;margin-bottom:20px;font-family:'Plus Jakarta Sans',sans-serif;color:#111827;outline:none;transition:border-color .15s;}}\n"
    "input:focus{{border-color:#00d165;}}\n"
    "button{{padding:11px 28px;background:#00d165;color:#080c14;border:none;border-radius:8px;font-weight:700;cursor:pointer;font-size:14px;font-family:'Plus Jakarta Sans',sans-serif;transition:background .15s;}}\n"
    "button:hover{{background:#04e270;}}"
)

if old_settings_css in src:
    src = src.replace(old_settings_css, new_settings_css)
    print('Settings CSS redesigned: done')
else:
    print('WARNING: Settings CSS not matched')

# ── 6. Redesign map-fields page CSS ───────────────────────────────────────
old_map_css = (
    "* {{ margin:0; padding:0; box-sizing:border-box; }}\n"
    "body {{ background:#f5faf5; font-family:'Plus Jakarta Sans',sans-serif; color:#0a1a0a; }}\n"
    ".topbar {{ background:#008000; padding:16px 40px; display:flex; align-items:center; justify-content:space-between; }}\n"
    ".topbar-logo {{ font-family:'Syne',sans-serif; font-size:22px; font-weight:800; color:#ffffff; }}\n"
    ".topbar-hotel {{ font-family:'JetBrains Mono',monospace; font-size:12px; color:rgba(255,255,255,0.8); }}\n"
    ".btn-nav {{ padding:8px 18px; background:rgba(255,255,255,0.15); border:1px solid rgba(255,255,255,0.3); border-radius:8px; color:#ffffff; font-size:13px; font-weight:600; text-decoration:none; }}\n"
    ".btn-nav:hover {{ background:rgba(255,255,255,0.25); }}\n"
    ".content {{ max-width:860px; margin:0 auto; padding:48px 24px; }}\n"
    ".page-title {{ font-family:'Plus Jakarta Sans',sans-serif; font-size:32px; font-weight:800; margin-bottom:6px; }}\n"
    ".page-sub {{ font-size:13px; color:#4a6648; font-family:'JetBrains Mono',monospace; margin-bottom:32px; }}\n"
    ".card {{ background:#ffffff; border:1px solid rgba(0,128,0,0.15); border-radius:16px; padding:32px; margin-bottom:24px; }}\n"
    ".card-title {{ font-family:'Plus Jakarta Sans',sans-serif; font-size:18px; font-weight:700; margin-bottom:6px; }}\n"
    ".card-sub {{ font-size:13px; color:#4a6648; margin-bottom:24px; }}\n"
    ".submit-btn {{ width:100%; padding:16px; background:#008000; color:white; border:none; border-radius:12px; font-weight:700; font-size:16px; cursor:pointer; font-family:'Plus Jakarta Sans',sans-serif; margin-top:8px; }}\n"
    ".submit-btn:hover {{ background:#006600; }}\n"
    "select:focus {{ border-color:#008000; background:white; }}"
)

new_map_css = (
    "*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box;}}\n"
    "body{{background:#f9fafb;font-family:'Plus Jakarta Sans',sans-serif;color:#111827;-webkit-font-smoothing:antialiased;}}\n"
    ".topbar{{background:#fff;border-bottom:1px solid #e5e7eb;padding:0 40px;height:56px;display:flex;align-items:center;justify-content:space-between;}}\n"
    ".topbar-logo{{font-family:'Syne',sans-serif;font-size:18px;font-weight:800;color:#111827;letter-spacing:-0.3px;}}\n"
    ".topbar-logo span{{color:#00d165;}}\n"
    ".topbar-hotel{{font-size:11px;color:#9ca3af;font-family:'JetBrains Mono',monospace;margin-top:2px;}}\n"
    ".btn-nav{{padding:7px 16px;background:#fff;border:1px solid #e5e7eb;border-radius:8px;color:#374151;font-size:13px;font-weight:500;text-decoration:none;transition:border-color .15s;display:inline-block;}}\n"
    ".btn-nav:hover{{border-color:#111827;color:#111827;}}\n"
    ".content{{max-width:860px;margin:0 auto;padding:48px 24px;}}\n"
    ".page-title{{font-size:28px;font-weight:700;color:#111827;letter-spacing:-0.5px;margin-bottom:6px;}}\n"
    ".page-sub{{font-size:12px;color:#9ca3af;font-family:'JetBrains Mono',monospace;margin-bottom:32px;}}\n"
    ".card{{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:28px;margin-bottom:20px;}}\n"
    ".card-title{{font-size:16px;font-weight:600;color:#111827;margin-bottom:6px;}}\n"
    ".card-sub{{font-size:13px;color:#6b7280;margin-bottom:20px;}}\n"
    ".submit-btn{{width:100%;padding:14px;background:#00d165;color:#080c14;border:none;border-radius:8px;font-weight:700;font-size:15px;cursor:pointer;font-family:'Plus Jakarta Sans',sans-serif;margin-top:8px;transition:background .15s;}}\n"
    ".submit-btn:hover{{background:#04e270;}}\n"
    "select:focus{{border-color:#00d165;background:white;outline:none;}}"
)

if old_map_css in src:
    src = src.replace(old_map_css, new_map_css)
    print('Map-fields CSS redesigned: done')
else:
    print('WARNING: Map-fields CSS not matched')

# ── 7. Update topbar HTML for settings + map-fields ───────────────────────
src = src.replace(
    '        <div class="topbar-logo">Occupado</div>\n        <div class="topbar-hotel">{hotel_name} · Map Your Data</div>',
    '        <div class="topbar-logo">Occup<span>ado</span></div>\n        <div class="topbar-hotel">{hotel_name} \xb7 Map Your Data</div>'
)
src = src.replace(
    '        <div class="topbar-logo">{t("occupado", lang)}</div>\n        <div class="topbar-hotel">{hotel_name} · {t("settings_title", lang)}</div>',
    '        <div class="topbar-logo">Occup<span>ado</span></div>\n        <div class="topbar-hotel">{hotel_name} \xb7 {t("settings_title", lang)}</div>'
)
print('Topbar HTML updated: done')

# ── 8. Fix generic dashboard topbar brand font ────────────────────────────
# Find .topbar-brand CSS and add Syne
src = src.replace(
    ".topbar-brand{{display:flex;align-items:center;gap:8px;}}",
    ".topbar-brand{{display:flex;align-items:center;gap:8px;font-family:'Syne',sans-serif;}}"
)
src = src.replace(
    ".topbar-brand{{display:flex;align-items:center;gap:6px;}}",
    ".topbar-brand{{display:flex;align-items:center;gap:6px;font-family:'Syne',sans-serif;}}"
)
print('Generic topbar brand: done')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(src)

print('\nAll done!')
