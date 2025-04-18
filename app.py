 from flask import Flask, render_template, request, redirect, url_for
-import os
+from flask import send_from_directory
+import os

 app = Flask(__name__)
 UPLOAD_FOLDER = "uploads"
 app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

 os.makedirs(UPLOAD_FOLDER, exist_ok=True)

 @app.route("/")
 def index():
     files = os.listdir(app.config["UPLOAD_FOLDER"])
     return render_template("index.html", files=files)

 @app.route("/upload", methods=["POST"])
 def upload():
     file = request.files["file"]
     if file:
         file.save(os.path.join(app.config["UPLOAD_FOLDER"], file.filename))
     return redirect(url_for("index"))

 @app.route("/delete/<filename>")
 def delete(filename):
     os.remove(os.path.join(app.config["UPLOAD_FOLDER"], filename))
     return redirect(url_for("index"))

 @app.route("/rename/<old_name>", methods=["POST"])
 def rename(old_name):
     new_name = request.form["new_name"]
     os.rename(
         os.path.join(app.config["UPLOAD_FOLDER"], old_name),
         os.path.join(app.config["UPLOAD_FOLDER"], new_name),
     )
     return redirect(url_for("index"))

+@app.route("/files/<path:filename>")
+def serve_file(filename):
+    # as_attachment=True forces download; remove if you want in-browser preview
+    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=True)

 # Run the app
 if __name__ == "__main__":
     app.run(debug=True)
