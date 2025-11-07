# app.py
import os
import uuid
import shlex
import subprocess
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash

# Setup
UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"
ALLOWED_EXT = {"mp4","mov","mkv","webm","mp3","wav","aac","m4a","flac","png","jpg","jpeg","wmv"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "devsecret")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["OUTPUT_FOLDER"] = OUTPUT_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024  # 1GB limit (adjust)

# Command templates (key -> template string).
# templates use placeholders: {in1}, {in2}, {in3}, {image}, {text}, {start}, {duration}, {scale_factor}, {out}
COMMAND_TEMPLATES = {
    "audio_cover": r'ffmpeg -i "{in1}" -i "{image}" -map 0 -map 1 -c copy -id3v2_version 3 -metadata:s:v title="{title}" -metadata:s:v comment="Cover (front)" "{out}"',
    "zoom_scale_crop_1.5": r'ffmpeg -i "{in1}" -vf "scale={scale_factor}*iw:-1,crop=ih*9/16:ih:({scale_factor}*iw-ih*9/16)/2:0,scale=720:1280" -preset ultrafast "{out}"',
    "zoom_scale_crop_1.0": r'ffmpeg -i "{in1}" -vf "scale=1.0*iw:-1, crop=ih*9/16:ih:(1.0*iw-ih*9/16)/2:(ih-ih)/2, scale=720:1280" -preset ultrafast "{out}"',
    "overlay_image": r'ffmpeg -i "{in1}" -i "{image}" -filter_complex "[0:v][1:v]overlay={overlay_x}:{overlay_y}" -map 0:a? -preset ultrafast "{out}"',
    "trim": r'ffmpeg -i "{in1}" -ss {start} -t {duration} -preset ultrafast "{out}"',
    "zoom_crop_simple": r'ffmpeg -i "{in1}" -vf "scale={scale_factor}*iw:-1, crop=iw/{scale_factor}:ih/{scale_factor}" -preset ultrafast "{out}"',
    "concat_two": r'ffmpeg -i "{in1}" -i "{in2}" -filter_complex "[0:0][0:1][1:0][1:1]concat=n=2:v=1:a=1[outv][outa]" -map "[outv]" -map "[outa]" "{out}"',
    "speedup_half_pts": r'ffmpeg -i "{in1}" -filter_complex "[0:v]setpts=0.5*PTS[v];[0:a]atempo=2.0[a]" -map "[v]" -map "[a]" -preset ultrafast "{out}"',
    "replace_audio_shortest": r'ffmpeg -i "{in1}" -i "{in2}" -c copy -map 0:v -map 1:a -shortest -preset ultrafast "{out}"',
    "vcodec_libx265": r'ffmpeg -i "{in1}" -vcodec libx265 -preset ultrafast "{out}"',
    "scale_fixed": r'ffmpeg -i "{in1}" -vf scale={scale_x}x{scale_y} "{out}"',
    "merge_video_audio_amerge": r'ffmpeg -i "{in1}" -i "{in2}" -c:v copy -filter_complex "[0:a]aformat=fltp:44100:stereo,apad[0a];[1]aformat=fltp:44100:stereo,volume={volume}[1a];[0a][1a]amerge[a]" -map 0:v -map "[a]" -ac 2 "{out}"',
    "video_overlay_and_audio_map": r'ffmpeg -i "{in1}" -i "{in2}" -i "{image}" -filter_complex "overlay={overlay_xy}" -map 0:v -map 1:a? -shortest -preset ultrafast "{out}"',
    "drawtext_split_overlay_motion": r'ffmpeg -i "{in1}" -filter_complex "[0:v]split[txt][orig];[txt]drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:fontsize={fontsize}:fontcolor={fontcolor}:x=(w-text_w)/2+{xoff}:y=h/2 + (h/3)*sin(2*PI*t/{period}):text=\'{text}\':enable=\'lt(mod(t\,60)\,60)\'[txt];[orig]crop=iw:50:0:0[orig];[txt][orig]overlay" -vcodec libx265 -preset ultrafast "{out}"',
    "drawtext_enable_crop_overlay": r'ffmpeg -i "{in1}" -filter_complex "[0:v]split[txt][orig];[txt]drawtext=fontfile={fontfile}:fontsize={fontsize}:fontcolor={fontcolor}:x=(w-text_w)/2+{xoff}:y=h-40*t:text=\'{text}\':enable=\'{enable}\'[txt];[orig]crop=iw:50:0:0[orig];[txt][orig]overlay" -vcodec libx265 -preset ultrafast "{out}"',
    "loop_image_to_video": r'ffmpeg -loop 1 -i "{image}" -i "{in1}" -c:v libx265 -c:a aac -b:a 192k -shortest -preset ultrafast "{out}"',
    "concat_copy": r'ffmpeg -f concat -safe 0 -i "{in1}" -c copy "{out}"',
    "change_codecs": r'ffmpeg -i "{in1}" -vcodec h264 -acodec mp2 "{out}"',
    "scale_bitrate": r'ffmpeg -i "{in1}" -vcodec h264 -b:v {bitrate} -acodec mp3 "{out}"',
    "add_metadata_vid_md5": r'ffmpeg -i "{in1}" -c:a libmp3lame -b:a {bitrate} -movflags use_metadata_tags -map_metadata 0 -metadata vid_md5="{vid_md5}" "{out}"',
    "concat_n": r'ffmpeg -i "{in1}" -i "{in2}" -i "{in3}" -filter_complex "[0:v][0:a][1:v][1:a][2:v][2:a]concat=n=3:v=1:a=1" -vsync vfr "{out}"',
    "transpose": r'ffmpeg -i "{in1}" -vf "transpose={transpose}" "{out}"',
    "eq_color": r'ffmpeg -i "{in1}" -vf "eq=brightness={brightness}:contrast={contrast}:saturation={saturation}:gamma={gamma}" -c:a copy "{out}"',
    "pad_and_overlay_volume": r'ffmpeg -i "{in1}" -i "{in2}" -filter_complex "[0:v]pad=iw*2:ih[v];[v][1:v]overlay=W/2:0[out_video];[0:a]volume={volume_db}dB[out_audio]" -map [out_video] -c:v libx265 -crf 28 -map [out_audio] -c:a aac -y "{out}"',
    "drawtext_simple_enable": r'ffmpeg -i "{in1}" -vf "drawtext=text=\'{text}\':fontcolor={fontcolor}:fontsize={fontsize}:x=(w-text_w)/2:y=(h-text_h)/2:enable=\'lt(mod(t,{mod_period}),{show_len})\'" -c:a copy "{out}"',
    "split_drawtext_overlay_vcodec_map_audio": r'ffmpeg -i "{in1}" -filter_complex "[0]split[txt][orig];[txt]drawtext=fontfile={fontfile}:fontsize={fontsize}:fontcolor={fontcolor}:x=(w-text_w)/2+{xoff}:y=h-40*t:text={text}:[txt];[orig]crop=iw:50:0:0[cropped];[txt][cropped]overlay" -vcodec libx265 -map 0:v -map 1:a -shortest -preset ultrafast "{out}"',
    "webp_gif_from_video": r'ffmpeg -i "{in1}" -vf "fps={fps},scale={scale_x}:-1:flags=lanczos" -c:v libwebp -loop 0 -an "{out}"',
    "reverse_webp": r'ffmpeg -i "{in1}" -vf "reverse,setpts=PTS*{pts_mul},scale={scale_x}:{scale_y}" -c:v libwebp -lossless 1 -loop 0 -an "{out}"',
    "concat_drawtext": r'ffmpeg -f concat -safe 0 -i "{in1}" -vf "drawtext=text=\'{text}\':fontcolor={fontcolor}:fontsize={fontsize}:x=(w-text_w)/2:y=(h-text_h)/2:enable=\'lt(mod(t,{mod_period}),{show_len})\'" -c:a copy "{out}"',
    "concat_with_audio_drawtext": r'ffmpeg -f concat -safe 0 -i "{in1}" -i "{in2}" -map 0:v -map 1:a -shortest -vf "drawtext=text=\'{text}\':fontcolor={fontcolor}:fontsize={fontsize}:x=(w-text_w)/2:y=(h-text_h)/2:enable=\'lt(mod(t,{mod_period}),{show_len})\'" -c:a copy "{out}"',
    "merge_video_and_audio_with_text_overlay": r'ffmpeg -i "{in1}" -i "{in2}" -filter_complex "[0]split[txt][orig];[txt]drawtext=fontfile={fontfile}:fontsize={fontsize}:fontcolor={fontcolor}:x=(w-text_w)/2+{xoff}:y=h-30*t:text=\'{text}\':[txt];[orig]crop=iw:50:0:0[orig];[txt][orig]overlay" -c copy -preset ultrafast "{out}"',
    "replace_map_metadata_shortest": r'ffmpeg -i "{in1}" -i "{in2}" -ss {start} -t {duration} -map 0:v -map 1:a -c:v libx265 -preset ultrafast -c:a copy -map_metadata -1 -shortest "{out}"',
    "pan_and_instrumental": r'ffmpeg -i "{in1}" -af "pan=stereo|c0=c0|c1=-1*c1" "{out}"',
    "create_lofi_filters": r'ffmpeg -i "{in1}" -af "lowpass=f=3000, highpass=f=200, aecho=0.8:0.9:1000:0.3, volume={volume}, dynaudnorm" "{out}"',
    # Add more templates here if desired...
}

# Utility helpers
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT

def save_uploaded(file_storage, prefix=""):
    filename = file_storage.filename
    ext = filename.rsplit(".", 1)[1] if "." in filename else "bin"
    uid = uuid.uuid4().hex[:10]
    safe = f"{prefix}_{uid}.{ext}"
    path = os.path.join(app.config["UPLOAD_FOLDER"], safe)
    file_storage.save(path)
    return path, safe

@app.route("/", methods=["GET"])
def index():
    # Provide list of commands for the dropdown
    commands = sorted(COMMAND_TEMPLATES.keys())
    return render_template("index.html", commands=commands)

@app.route("/build-preview", methods=["POST"])
def build_preview():
    # AJAX endpoint to generate command preview (not executing)
    selection = request.form.get("command_key")
    if not selection or selection not in COMMAND_TEMPLATES:
        return {"ok": False, "cmd": "", "error": "Invalid command key"}, 400

    # Form parameters (we accept many optional fields)
    params = {}
    for k in request.form:
        params[k] = request.form.get(k)

    # Map inputs (we do not save files here). We only fill placeholders with user-supplied values.
    # Important placeholders default handling:
    defaults = {
        "in1": "input1.ext",
        "in2": "input2.ext",
        "in3": "input3.ext",
        "image": "cover.png",
        "title": "Title",
        "text": "TOWSIF AKTAR",
        "fontsize": "20",
        "fontcolor": "gray",
        "xoff": "20",
        "period": "5",
        "scale_factor": "1.5",
        "overlay_x": "10",
        "overlay_y": "10",
        "overlay_xy": "01:00",
        "start": "00:00:00",
        "duration": "00:03:15",
        "scale_x": "640",
        "scale_y": "360",
        "fps": "15",
        "pts_mul": "2",
        "bitrate": "128k",
        "vid_md5": "4032e3631edbed8efbfbabf97b5312d7",
        "volume": "1.5",
        "volume_db": "20",
        "fontsize": "24",
        "mod_period": "60",
        "show_len": "1",
        "transpose": "1",
        "brightness": "0.1",
        "contrast": "1.2",
        "saturation": "1.5",
        "gamma": "1.0"
    }

    # Merge params with defaults and format template
    tmpl = COMMAND_TEMPLATES[selection]
    fill = {}
    for k, v in defaults.items():
        fill[k] = params.get(k, v)

    # Also copy through any direct form fields user gave (title, text, etc.)
    for k, v in params.items():
        if v:
            fill[k] = v

    # temp out placeholder
    fill["out"] = params.get("outname", "output_processed." + (fill.get("in1","input1.ext").rsplit(".",1)[-1] if "." in fill.get("in1","input1.ext") else "mp4"))

    # Format safely (we do minimal escaping for preview)
    try:
        cmd = tmpl.format(**fill)
    except Exception as e:
        return {"ok": False, "cmd": "", "error": f"Formatting error: {e}"}, 500

    return {"ok": True, "cmd": cmd}

@app.route("/process", methods=["POST"])
def process():
    # Save uploaded files (up to 3) and map to placeholders in templates
    files = {}
    for idx in (1,2,3):
        f = request.files.get(f"file{idx}")
        if f and f.filename and allowed_file(f.filename):
            path, safe = save_uploaded(f, prefix=f"input{idx}")
            files[f"in{idx}"] = path
            files[f"safe{idx}"] = safe

    # image upload
    img = request.files.get("image")
    if img and img.filename and allowed_file(img.filename):
        path_img, safe_img = save_uploaded(img, prefix="image")
        files["image"] = path_img
        files["safe_image"] = safe_img

    # get chosen command
    selection = request.form.get("command_key")
    if not selection or selection not in COMMAND_TEMPLATES:
        flash("Invalid command selection.")
        return redirect(url_for("index"))

    tmpl = COMMAND_TEMPLATES[selection]

    # Build fill dict from form values + uploaded file paths
    fill = {}
    # map uploaded in1/in2/in3 to actual saved paths (quotes handled in template)
    for i in (1,2,3):
        key = f"in{i}"
        if key in files:
            fill[key] = files[key]
        else:
            # fall back to user-specified path string if provided
            user_val = request.form.get(key)
            fill[key] = user_val or f"{key}.ext"

    if "image" in files:
        fill["image"] = files["image"]
    else:
        fill["image"] = request.form.get("image") or "cover.png"

    # Fill other parameters from form
    for param in ("title","text","start","duration","scale_factor","scale_x","scale_y",
                  "overlay_x","overlay_y","overlay_xy","fontsize","fontcolor","xoff",
                  "period","volume","volume_db","bitrate","vid_md5","fps","pts_mul",
                  "mod_period","show_len","transpose","brightness","contrast","saturation","gamma",
                  "fontfile","outname"):
        v = request.form.get(param)
        if v:
            fill[param] = v

    # default out name if not given
    if "outname" in request.form and request.form.get("outname"):
        outname = request.form.get("outname")
    else:
        # create unique out filename in outputs
        ext = "mp4"
        if selection == "audio_cover":
            ext = files.get("safe1", "out.mp3").rsplit(".",1)[-1] if "safe1" in files else "mp3"
        elif selection.startswith("webp") or selection=="webp_gif_from_video" or selection=="reverse_webp":
            ext = "webp"
        elif selection in ("concat_copy","concat_n","concat_drawtext","concat_with_audio_drawtext"):
            ext = "mp4"
        elif "in1" in fill and "." in fill["in1"]:
            ext = fill["in1"].rsplit(".",1)[-1]
        outname = f"out_{uuid.uuid4().hex[:8]}.{ext}"
    fill["out"] = os.path.join(app.config["OUTPUT_FOLDER"], outname)

    # Provide sane defaults for missing fields to avoid KeyError
    defaults = {
        "scale_factor": "1.5", "fontsize":"20","fontcolor":"gray","xoff":"20",
        "period":"5","start":"00:00:00","duration":"00:03:15","overlay_x":"10",
        "overlay_y":"10","overlay_xy":"01:00","scale_x":"640","scale_y":"360",
        "volume":"1.5","volume_db":"20","bitrate":"128k","vid_md5":"md5hash",
        "fps":"15","pts_mul":"2","mod_period":"60","show_len":"1","transpose":"1",
        "brightness":"0.1","contrast":"1.2","saturation":"1.5","gamma":"1.0",
        "fontfile":"/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    }
    for k,v in defaults.items():
        if k not in fill:
            fill[k] = v

    # Format template -> final command
    try:
        ffmpeg_cmd = tmpl.format(**fill)
    except Exception as e:
        flash(f"Template formatting error: {e}")
        return redirect(url_for("index"))

    # Run ffmpeg (shell=True because many templates include complex syntax)
    try:
        # Make sure output folder exists
        os.makedirs(app.config["OUTPUT_FOLDER"], exist_ok=True)
        # Execute
        proc = subprocess.run(ffmpeg_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=900)
        if proc.returncode != 0:
            flash("FFmpeg failed: see server log for details.")
            # store last log file
            logname = f"log_{uuid.uuid4().hex[:8]}.txt"
            with open(os.path.join(app.config["OUTPUT_FOLDER"], logname), "w", encoding="utf-8") as fh:
                fh.write(ffmpeg_cmd + "\n\n=== OUTPUT ===\n")
                fh.write(proc.stdout)
            flash(f"Saved FFmpeg output to {logname}")
            return redirect(url_for("index"))
    except subprocess.TimeoutExpired:
        flash("FFmpeg timed out.")
        return redirect(url_for("index"))
    except Exception as e:
        flash(f"Error running FFmpeg: {e}")
        return redirect(url_for("index"))

    # Provide download link
    return redirect(url_for("download_file", filename=outname))

@app.route("/downloads/<path:filename>", methods=["GET"])
def download_file(filename):
    return send_from_directory(app.config["OUTPUT_FOLDER"], filename, as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
