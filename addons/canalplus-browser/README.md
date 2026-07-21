# Canal+ Browser Helper Add-on Scaffold

This add-on scaffold packages the browser dependencies for the Canal+ PoC in an isolated container image.

It is intentionally idle by default. The local wrapper script in `scripts/run_canalplus_browser_container.sh` builds this image and runs `scripts/canalplus_poc.py` inside it when you pass a command such as `browser-normalized-epg`.

The image keeps Playwright and Chromium out of HAOS itself. It only covers the Canal+ browser-session side of the workflow; it does not read Home Assistant Open EPG sensors. If you later turn this into a full Home Assistant add-on or HA-side bridge, this folder is the starting point.