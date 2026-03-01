import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const approvalsPagePath = path.join(__dirname, "../src/pages/admin/approvals/index.tsx");
const source = fs.readFileSync(approvalsPagePath, "utf8");

test("approvals page imports listApprovals API", () => {
  assert.match(source, /listApprovals/);
});

test("approvals page imports createApproval API", () => {
  assert.match(source, /createApproval/);
});

test("approvals page imports revokeApproval API", () => {
  assert.match(source, /revokeApproval/);
});

test("approvals page imports ApprovalRecord type", () => {
  assert.match(source, /ApprovalRecord/);
});

test("approvals page has create approval modal", () => {
  assert.match(source, /CreateApprovalModal/);
  assert.match(source, /Create Approval Token/);
});

test("approvals page shows action, target_ref, and TTL fields", () => {
  assert.match(source, /Target Ref/);
  assert.match(source, /ttl_minutes|TTL/);
  assert.match(source, /action/);
});

test("approvals page has revoke action on rows", () => {
  assert.match(source, /Revoke/);
  assert.match(source, /revokeApproval|revokeMutation/);
});

test("approvals page has status filter", () => {
  assert.match(source, /statusFilter/);
  assert.match(source, /All statuses/);
});

test("approvals page has action filter", () => {
  assert.match(source, /actionFilter/);
  assert.match(source, /All actions/);
});

test("approvals page displays allowed actions from API", () => {
  assert.match(source, /allowedActions/);
  assert.match(source, /allowed_actions/);
});

// Verify types file has ApprovalRecord
const typesPath = path.join(__dirname, "../src/types/index.ts");
const typesSource = fs.readFileSync(typesPath, "utf8");

test("types/index.ts exports ApprovalRecord", () => {
  assert.match(typesSource, /export interface ApprovalRecord/);
});

test("types/index.ts exports FeatureBuildRun", () => {
  assert.match(typesSource, /export interface FeatureBuildRun/);
});

test("types/index.ts has FeatureRequest with approval_status", () => {
  assert.match(typesSource, /approval_status/);
  assert.match(typesSource, /export interface FeatureRequest/);
});
