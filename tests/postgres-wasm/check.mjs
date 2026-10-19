// Supplemental real PostgreSQL/WASM DDL check, without a daemon or privileged OS user.
// Does not replace psycopg networking, container or role-isolation integration tests.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { PGlite } from '@electric-sql/pglite';

const root = fileURLToPath(new URL('../..', import.meta.url));
function sql(args) {
  return execFileSync('uv', ['run', 'alembic', '-c', 'backend/alembic.ini', ...args, '--sql'], {
    cwd: root,
    env: { ...process.env, DKMAN_DATABASE_URL: 'postgresql+psycopg://localhost/dkman_test' },
    encoding: 'utf8',
  });
}
const up = sql(['upgrade', 'head']);
const down = sql(['downgrade', '0001_foundation:base']);
const db = new PGlite();
try {
  const version = await db.query('SELECT version() AS version');
  console.log(version.rows[0].version);
  await db.exec(up);
  const revision = await db.query('SELECT version_num FROM alembic_version');
  assert.equal(revision.rows[0].version_num, '0001_foundation');
  const tables = await db.query("SELECT tablename FROM pg_tables WHERE schemaname='public'");
  assert.equal(tables.rows.length, 12);
  await assert.rejects(
    db.query("INSERT INTO permission_grants (id, created_at, installation_id, subject, permission) VALUES ('test', now(), 'missing', 'alice', 'app.use')"),
    { code: '23503' },
  );
  await db.exec(down);
  const empty = await db.query("SELECT tablename FROM pg_tables WHERE schemaname='public'");
  assert.deepEqual(empty.rows, [{ tablename: 'alembic_version' }]);
  const noRevision = await db.query('SELECT version_num FROM alembic_version');
  assert.equal(noRevision.rows.length, 0);
  // Offline upgrade SQL assumes a fresh version table; online Alembic handles this itself.
  await db.exec('DROP TABLE alembic_version');
  await db.exec(up);
  console.log('PASS: upgrade, revision, 12 tables, FK rejection, downgrade, re-upgrade');
} finally {
  await db.close();
}
