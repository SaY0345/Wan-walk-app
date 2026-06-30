const SPREADSHEET_ID = "YOUR_SPREADSHEET_ID";
const WORKSHEET_NAME = "measurements";
const REQUIRED_TOKEN = "OPTIONAL_SHARED_TOKEN";

const MEASUREMENT_COLUMNS = [
  "日時",
  "地点",
  "予測温度",
  "補正後予測温度",
  "実測温度",
  "差分",
  "路面",
  "メモ",
  "データソース",
  "気温",
  "雲量",
  "風速",
  "降水量",
  "日射",
  "昼フラグ",
];

function doGet(e) {
  try {
    if (!isAuthorized_(e, null)) {
      return jsonResponse_({ status: "error", message: "Unauthorized" });
    }

    const sheet = getWorksheet_();
    const values = sheet.getDataRange().getValues();
    if (!values.length) {
      ensureHeader_(sheet);
      return jsonResponse_({ status: "ok", rows: [] });
    }

    const headers = values[0];
    const rows = values
      .slice(1)
      .filter((row) => row.some((value) => value !== ""))
      .map((row) => {
        const record = {};
        headers.forEach((header, index) => {
          record[header] = row[index];
        });
        return record;
      });

    return jsonResponse_({ status: "ok", rows });
  } catch (error) {
    return jsonResponse_({ status: "error", message: String(error) });
  }
}

function doPost(e) {
  try {
    const payload = parsePayload_(e);
    if (!isAuthorized_(e, payload)) {
      return jsonResponse_({ status: "error", message: "Unauthorized" });
    }

    const record = payload.record || payload;
    const sheet = getWorksheet_();
    ensureHeader_(sheet);

    const row = MEASUREMENT_COLUMNS.map((column) => {
      const value = record[column];
      return value === undefined || value === null ? "" : value;
    });
    sheet.appendRow(row);

    return jsonResponse_({ status: "ok" });
  } catch (error) {
    return jsonResponse_({ status: "error", message: String(error) });
  }
}

function getWorksheet_() {
  const spreadsheet = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sheet = spreadsheet.getSheetByName(WORKSHEET_NAME);
  if (sheet) {
    return sheet;
  }
  return spreadsheet.insertSheet(WORKSHEET_NAME);
}

function ensureHeader_(sheet) {
  const currentHeader = sheet
    .getRange(1, 1, 1, MEASUREMENT_COLUMNS.length)
    .getValues()[0];
  const headerMatches = MEASUREMENT_COLUMNS.every(
    (column, index) => currentHeader[index] === column,
  );
  if (!headerMatches) {
    sheet.getRange(1, 1, 1, MEASUREMENT_COLUMNS.length).setValues([MEASUREMENT_COLUMNS]);
  }
}

function parsePayload_(e) {
  if (!e || !e.postData || !e.postData.contents) {
    return {};
  }
  return JSON.parse(e.postData.contents);
}

function isAuthorized_(e, payload) {
  if (!REQUIRED_TOKEN) {
    return true;
  }

  const paramToken = e && e.parameter ? e.parameter.token : "";
  const payloadToken = payload && payload.token ? payload.token : "";
  return paramToken === REQUIRED_TOKEN || payloadToken === REQUIRED_TOKEN;
}

function jsonResponse_(payload) {
  return ContentService.createTextOutput(JSON.stringify(payload)).setMimeType(
    ContentService.MimeType.JSON,
  );
}
