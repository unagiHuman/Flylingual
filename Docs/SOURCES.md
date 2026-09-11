# 参照資料と確認範囲

確認日：2026-09-11 JST

## S01 — MaleCNS公式概要
https://male-cns.janelia.org/

公式サイトでMaleCNS v1.0、脳＋VNCの対象、共同研究主体、公開履歴を確認。発表済みのデータ構造と、今回独自に作る動的モデルを区別するために使用。

## S02 — MaleCNS公式配布
https://male-cns.janelia.org/download/

必要なannotation／NT／weightsの正確なファイル名、13MB／42MB／1.1GBの記載、全segment間connection graphであること、CC-BYの表示、neuPrint dataset名を確認。

配布Featherの全バイト・実schemaはこの手順書作成環境では未取得。手順のM2で実機が確認する。HTTPバイト取得やSHAは利用端末で生成する。

## S03 — natverse/malecns
https://natverse.org/malecns/
https://github.com/natverse/malecns

`flywireType`、`mancType`等の対応metadataを提供することを確認。これをIDの同一性や生理学的機能の完全な同一性の保証として使わない。

## S04 — 既存Shiuモデル
https://github.com/philshiu/Drosophila_brain_model/blob/main/model.py
https://github.com/philshiu/Drosophila_brain_model/blob/main/Readme.md
https://www.nature.com/articles/s41586-024-07763-9

公開model.pyのBrian2構造、疎なpre/post入力、符号付き重み、Poisson刺激、trial内のnetwork構築を確認。公開model.py取得時blob SHA：`5ba7083cf55bf6092967f8d9065e86cd677efed1`。

ユーザーが作成したpersistent/Server/Unityコードはこの公開リポジトリそのものではない。会話の実測報告を出発点とし、Codexがローカル現物を確認する。

## S05 — Brian2 2.5.1の導入
https://brian2.readthedocs.io/en/2.5.1/introduction/install.html

独立環境の推奨、Cython/C++ compiler、Windows Visual Studio Build Toolsの要件を確認。最新版Brian2へupgradeする根拠としては使用していない。

## S06 — conda環境管理
https://docs.conda.io/projects/conda/en/latest/user-guide/tasks/manage-environments.html
https://docs.conda.io/projects/conda/en/24.7.x/user-guide/tasks/manage-environments.html

環境複製、export、cross-platform exportの注意点。実機のcondaバージョンと--helpも確認する。成功したMac環境は同OS内でcloneし、WindowsへはOS固有buildをコピーしない。

## S07 — Unity外部バージョン管理
https://docs.unity3d.com/es/2020.1/Manual/ExternalVersionControlSystemSupport.html

Assets／Packages／ProjectSettings／.metaを管理し、Libraryをローカルcacheとして扱う一般原則を確認。これはユーザーの6000.5.5f1プロジェクトの実機検証ではない。

## S08 — OpenAI Codex MCP
https://developers.openai.com/codex/mcp/

閲覧時はOpenAIのChatGPT Learn MCP文書へredirect。STDIO MCP、Codex hostでの設定共有、CLI設定を確認。実行端末のCLI --helpも確認する。

## S09 — Blender MCP（第三者製）
https://github.com/ahujasid/blender-mcp/blob/main/README.md

Codex登録コマンド、`install-addon`、Blender addon起動、任意Python実行、1接続での操作、uvの独立Python利用を確認。取得時README blob SHA：`73964da17c2a7c8ca57e5065af13e3bf87be3bed`。

これはBlender Foundation公式ツールではない。実機の導入・権限・外部送信は別途確認する。

## S10 — Blenderのノード材質export
https://docs.blender.org/manual/en/4.1/addons/import_export/node_shaders_info.html

FBX等への材質変換は対応するnode構成・image texturesに制約があり、任意のBlender node graphをUnity shaderへ完全変換できるとは限らないことを確認。Unity向けのbake／材質再構成は本手順の設計提案。

## S11 — OpenAI AGENTS.md
https://developers.openai.com/codex/guides/agents-md/

Codexへのリポジトリ内作業指示としてAGENTS.mdを使うことを確認。共通契約や担当分離の内容そのものは本プロジェクト向けの提案。

## ユーザー報告に基づくもの

Mac/Unityの実行パス、Unity 6000.5.5f1、Cython 0.29.37、50ms window・約180ms計算、E2E約358ms、18関節、FootPad・adhesion実績等は会話の報告を基準としている。こちらでユーザーのローカルファイルへアクセスして再実行した結果ではない。

## 今回採用していない根拠

第三者のMaleCNSゲームデモのMac性能、特定GPUでの高速化倍率、以前の会話にあるedge数を、そのまま今回のLIF実装の性能保証に使っていない。正確なN/E・RSS・速度は本手順の実測対象。
