/**
 * google_apps_script.gs
 * ---------------------
 * Receives data from index.html and writes it into a Google Drive folder.
 *
 * SET-UP (once; full walk-through in README.md)
 *   1. Create a folder in Google Drive for the data. Open it; the folder ID is the last part
 *      of the URL:  https://drive.google.com/drive/folders/<FOLDER_ID>
 *   2. Go to https://script.google.com  ->  New project. Delete the default code and paste this file.
 *   3. Put your folder ID in FOLDER_ID below and save (Ctrl/Cmd+S).
 *   4. Deploy -> New deployment -> type: Web app.
 *        Execute as:      Me
 *        Who has access:  Anyone
 *      Click Deploy, authorise when asked (it needs Drive access to write the files),
 *      and copy the Web app URL (ends in /exec).
 *   5. Paste that URL into CONFIG.save_url in index.html.
 *   6. Test: open the Web app URL in a browser tab -> you should see {"status":"ok","message":"receiver is up"}.
 *
 *   IMPORTANT: every time you edit this script you must Deploy -> Manage deployments -> Edit ->
 *   Version: New version -> Deploy, otherwise the live URL keeps running the old code.
 *
 * WHAT IT WRITES  (per participant session)
 *   <filename>.json          full jsPsych data incl. hand/dot trajectories
 *   <filename>_summary.csv   one row per stretch/rating, no trajectories
 *   Partial saves at block breaks overwrite the same two files, so a drop-out still leaves data.
 *   A row is appended to _log.csv in the folder for every save (time, pid, final?, size).
 */

var FOLDER_ID = 'PASTE_YOUR_DRIVE_FOLDER_ID_HERE';

function doGet(e) {
  return respond({ status: 'ok', message: 'receiver is up' });
}

function doPost(e) {
  try {
    if (!e || !e.postData || !e.postData.contents) {
      return respond({ status: 'error', message: 'no data received' });
    }
    var payload = JSON.parse(e.postData.contents);
    var folder  = DriveApp.getFolderById(FOLDER_ID);

    var name = String(payload.filename || ('data_' + new Date().toISOString()))
                 .replace(/[^A-Za-z0-9_\-]/g, '_');

    var written = [];
    if (payload.json) { writeOrReplace(folder, name + '.json', payload.json, MimeType.PLAIN_TEXT); written.push(name + '.json'); }
    if (payload.csv)  { writeOrReplace(folder, name + '_summary.csv', payload.csv, MimeType.CSV); written.push(name + '_summary.csv'); }

    appendLog(folder, [new Date().toISOString(), payload.pid || '', payload.final ? 'final' : 'partial',
                       (payload.json || '').length, written.join(' ')]);

    return respond({ status: 'ok', files: written });
  } catch (err) {
    return respond({ status: 'error', message: String(err) });
  }
}

/** Overwrite a file of this name if it exists in the folder, otherwise create it. */
function writeOrReplace(folder, name, content, mime) {
  var it = folder.getFilesByName(name);
  if (it.hasNext()) {
    var f = it.next();
    f.setContent(content);
    return f;
  }
  return folder.createFile(name, content, mime);
}

/** Append one line to _log.csv (created on first use). */
function appendLog(folder, fields) {
  var line = fields.map(function (v) { return '"' + String(v).replace(/"/g, '""') + '"'; }).join(',') + '\n';
  var it = folder.getFilesByName('_log.csv');
  if (it.hasNext()) {
    var f = it.next();
    f.setContent(f.getBlob().getDataAsString() + line);
  } else {
    folder.createFile('_log.csv', 'time,pid,kind,json_chars,files\n' + line, MimeType.CSV);
  }
}

function respond(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
                       .setMimeType(ContentService.MimeType.JSON);
}
