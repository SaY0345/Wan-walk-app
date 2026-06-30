# Wan Walk

犬の散歩向けアスファルト温度予測アプリ

## 機能

・気温取得
・路面温度推定
・実測値の保存
・実測にもとづく予測補正
・おすすめ散歩時間表示
・スマホ対応

## 使用API
・Open-Meteo

## 実行

streamlit run app.py

## スマホ入力で使う場合

・自宅PCだけで使うなら、ローカル起動でも入力できます
・外出先からもスマホで入力するなら、private GitHub repo + private Streamlit app を想定しています
・永続保存には Google Apps Script Webアプリか Google Sheets を使えます
・Google Cloud のサービスアカウントを使いたくない場合は `apps_script_example.gs` の方式が軽量です
・永続保存には Google Sheets を使えます。設定例は `.streamlit/secrets.toml.example` を参照してください
・Google Sheets を使うと、実測値はスプレッドシートに保存され、アプリ再起動後も残ります
・Apps Script Webアプリを使う場合も、実測値は Google スプレッドシートに保存され、アプリ再起動後も残ります
・Google Sheets 未設定時は `data/measurements.csv` に保存します

## 精度改善の流れ

・実測メモを保存すると `data/measurements.csv` に蓄積されます
・手入力した実測には、その時点の気温・雲量・風速・降水・日射も保存されます
・`temple.csv` を置くと、2行ヘッダー付きの実測表を自動で取り込みます
・アスファルト実測が3件以上たまると固定補正、8件以上あると線形補正も含めて最適な補正式を自動選択します
・手入力の実測が8件以上たまると、日射・風・雨・夜間・安全マージン係数の再検証を始めます
・気象データは `data/weather_cache/` に保存され、取得から1時間以上経っていれば再取得して再予測します
・地点ごとの実測が少ない間は、取り込み済みの全体実測も使って補正します

## v0.1.0
・UI改善
・肉球背景
・地点表示改善
・Open-Meteo復旧
