-- 工作区/case.db 的表结构（契约 1.2：新增 material_ids 表，见文末；schema_version 仍为 1——第一版尚未发布，用 CREATE TABLE IF NOT EXISTS 补建即可）
-- 读写 case.db 的模块：案件（case/）、识别队列（ocr/）、检索（search/）。改表结构要升 schema_version，并在升级前备份为 case.db.bak-<旧版本>。
-- 成果登记不在这里，在 成果/索引.json（避免两处各记一份）。

PRAGMA journal_mode = WAL;

-- 案件元数据
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,   -- 固定键：case_id、schema_version、created_at
  value TEXT NOT NULL
);
-- INSERT INTO meta VALUES ('schema_version', '1');

-- 识别任务（一条 = 律师点一次"提交识别"）
CREATE TABLE IF NOT EXISTS ocr_jobs (
  job_id           TEXT PRIMARY KEY,           -- J-YYYYMMDDHHMMSS-xxxx
  material_id      TEXT NOT NULL,              -- M0001
  material_version TEXT NOT NULL,              -- 提交时原件的 sha256
  dewatermark      INTEGER NOT NULL DEFAULT 0, -- 0 / 1
  status           TEXT NOT NULL CHECK (status IN ('queued','running','paused','done','cancelled','partial_failed')),
  pause_reason     TEXT CHECK (pause_reason IN ('offline','prep_down','key_invalid','app_exit')),
  total            INTEGER NOT NULL,
  done             INTEGER NOT NULL DEFAULT 0,
  failed           INTEGER NOT NULL DEFAULT 0,
  created_at       TEXT NOT NULL,              -- ISO 8601
  updated_at       TEXT NOT NULL
);

-- 识别页（一条 = 一页；job_id + page_no 唯一，结果写入幂等）
CREATE TABLE IF NOT EXISTS ocr_pages (
  job_id      TEXT NOT NULL REFERENCES ocr_jobs(job_id),
  page_no     INTEGER NOT NULL,
  status      TEXT NOT NULL CHECK (status IN ('pending','sending','done','failed','cancelled')),
  attempts    INTEGER NOT NULL DEFAULT 0,
  error       TEXT,                            -- 中文原因；不含正文
  result_path TEXT,                            -- 工作区/材料/识别页/<material_id>/<page_no>.md
  PRIMARY KEY (job_id, page_no)
);

-- 检索单元：一页 / 一段 / 一个工作表的每 20 行 / 文本文件的每 50 行
CREATE TABLE IF NOT EXISTS search_units (
  rowid            INTEGER PRIMARY KEY,
  material_id      TEXT NOT NULL,
  material_version TEXT NOT NULL,
  unit             TEXT NOT NULL CHECK (unit IN ('page','para','cell','line')),
  loc_from         INTEGER,                    -- page/para/line：起始号；cell：工作表内起始行号
  loc_to           INTEGER,
  sheet            TEXT,                       -- 仅 cell
  is_ocr           INTEGER NOT NULL DEFAULT 0,
  text             TEXT NOT NULL,              -- 原文
  text_norm        TEXT NOT NULL               -- 归一化文本（全角转半角、去千分位、统一空白）
);
CREATE INDEX IF NOT EXISTS idx_units_material ON search_units(material_id);

-- FTS5 外部内容表，trigram 分词；1–2 字查询不走这里，改在 search_units.text_norm 上 instr 扫描
CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
  text_norm, content='search_units', content_rowid='rowid', tokenize='trigram'
);

-- 1.2 新增：材料编号留底（候 owner 清单 N26）。index.json 是材料索引的主本；这张表只为 index.json 丢失后重建时让同一份原件拿回原来的编号、新编号不占用旧的。
-- 写入时机：导入或扫描分配新编号时同步写一行；原件改名或移动视为删除后新增（Spec 4.1），旧行保留不删。
CREATE TABLE IF NOT EXISTS material_ids (
  material_id TEXT PRIMARY KEY,               -- M0001；同一案件内永不复用
  rel_path    TEXT NOT NULL,                  -- 分配编号时的原件相对路径（Windows 反斜杠换成 /）
  sha256      TEXT NOT NULL,                  -- 分配编号时原件的 sha256
  first_seen  TEXT NOT NULL                   -- ISO 8601
);
CREATE INDEX IF NOT EXISTS material_ids_rel_path ON material_ids(rel_path);
-- meta 里另存 next_material_seq（下一个可用序号），重建 index.json 时以 max(meta.next_material_seq, 表内最大编号+1) 为起点。
