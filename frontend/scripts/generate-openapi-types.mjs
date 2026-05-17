import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const root = path.resolve(__dirname, '..');
const schemaPath = path.join(root, 'openapi.json');
const generatedPath = path.join(root, 'src', 'generated', 'openapi.ts');
const metaPath = path.join(root, 'src', 'types', 'openapi-contract.ts');
const apiTypesPath = path.join(root, 'src', 'types', 'api.ts');

if (!fs.existsSync(schemaPath)) {
  console.error(`OpenAPI schema not found: ${schemaPath}`);
  process.exit(1);
}

const raw = fs.readFileSync(schemaPath, 'utf8');
const schema = JSON.parse(raw);
const hash = crypto.createHash('sha256').update(raw).digest('hex');
const routeEntries = Object.entries(schema.paths ?? {});
const operationIds = routeEntries.flatMap(([, operations]) => (
  Object.values(operations ?? {})
    .map((operation) => operation?.operationId)
    .filter((value) => typeof value === 'string')
)).sort();

const INDENT = '  ';
const schemaNames = Object.keys(schema.components?.schemas ?? {});

function indent(level) {
  return INDENT.repeat(level);
}

function literal(value) {
  if (typeof value === 'string') return JSON.stringify(value);
  if (value === null) return 'null';
  return String(value);
}

function escapeKey(value) {
  return /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(value) ? value : JSON.stringify(value);
}

function wrapIfNeeded(type) {
  return /\s[|&]\s/.test(type) ? `(${type})` : type;
}

function unique(items) {
  return [...new Set(items.filter(Boolean))];
}

function refToTs(ref) {
  const match = ref.match(/^#\/components\/schemas\/(.+)$/);
  if (match) {
    return `components['schemas'][${JSON.stringify(match[1])}]`;
  }
  return 'unknown';
}

function emitObjectType(schemaNode, level) {
  const props = schemaNode.properties ?? {};
  const required = new Set(schemaNode.required ?? []);
  const entries = [];
  for (const [propName, propSchema] of Object.entries(props)) {
    const optional = required.has(propName) ? '' : '?';
    entries.push(`${indent(level + 1)}${escapeKey(propName)}${optional}: ${emitSchema(propSchema, level + 1)};`);
  }

  const additional = schemaNode.additionalProperties;
  if (additional !== undefined) {
    if (!Object.keys(props).length) {
      if (additional === true) return 'Record<string, unknown>';
      if (additional === false) return 'Record<string, never>';
      return `Record<string, ${emitSchema(additional, level)}>`;
    }
    if (additional === true) {
      entries.push(`${indent(level + 1)}[key: string]: unknown;`);
    } else if (additional !== false) {
      entries.push(`${indent(level + 1)}[key: string]: ${emitSchema(additional, level + 1)};`);
    }
  }

  if (!entries.length) return 'Record<string, unknown>';
  return `{
${entries.join('\n')}
${indent(level)}}`;
}

function emitSchema(schemaNode, level = 0) {
  if (!schemaNode || typeof schemaNode !== 'object') return 'unknown';
  if (schemaNode.$ref) return refToTs(schemaNode.$ref);
  if (schemaNode.const !== undefined) return literal(schemaNode.const);
  if (Array.isArray(schemaNode.enum)) {
    return schemaNode.enum.length ? schemaNode.enum.map(literal).join(' | ') : 'never';
  }
  if (Array.isArray(schemaNode.anyOf) && schemaNode.anyOf.length) {
    return unique(schemaNode.anyOf.map((item) => emitSchema(item, level))).join(' | ');
  }
  if (Array.isArray(schemaNode.oneOf) && schemaNode.oneOf.length) {
    return unique(schemaNode.oneOf.map((item) => emitSchema(item, level))).join(' | ');
  }
  if (Array.isArray(schemaNode.allOf) && schemaNode.allOf.length) {
    return unique(schemaNode.allOf.map((item) => emitSchema(item, level))).join(' & ');
  }
  if (Array.isArray(schemaNode.type)) {
    return unique(schemaNode.type.map((entry) => emitSchema({ ...schemaNode, type: entry }, level))).join(' | ');
  }
  if (schemaNode.type === 'array') {
    return `${wrapIfNeeded(emitSchema(schemaNode.items ?? {}, level))}[]`;
  }
  if (schemaNode.type === 'object' || schemaNode.properties || schemaNode.additionalProperties !== undefined) {
    return emitObjectType(schemaNode, level);
  }
  switch (schemaNode.type) {
    case 'string':
      return 'string';
    case 'integer':
    case 'number':
      return 'number';
    case 'boolean':
      return 'boolean';
    case 'null':
      return 'null';
    default:
      return 'unknown';
  }
}

function normalizePathKey(pathKey) {
  const normalized = pathKey.replace(/^\/api\/v1/, '');
  return normalized || '/';
}

function emitContent(content, level) {
  const entries = Object.entries(content ?? {});
  if (!entries.length) return 'Record<string, never>';
  const lines = entries.map(([mediaType, media]) => `${indent(level + 1)}${JSON.stringify(mediaType)}: ${emitSchema(media?.schema ?? {}, level + 1)};`);
  return `{
${lines.join('\n')}
${indent(level)}}`;
}

function emitRequestBody(requestBody, level) {
  if (!requestBody) return null;
  const optional = requestBody.required ? '' : '?';
  return `${indent(level)}requestBody${optional}: {
${indent(level + 1)}content: ${emitContent(requestBody.content, level + 1)};
${indent(level)}};`;
}

function emitParameters(parameters, level) {
  if (!Array.isArray(parameters) || !parameters.length) return null;
  const groups = new Map();
  for (const parameter of parameters) {
    const group = groups.get(parameter.in) ?? [];
    group.push(parameter);
    groups.set(parameter.in, group);
  }
  const groupLines = [];
  for (const [groupName, items] of groups.entries()) {
    const props = items.map((parameter) => {
      const optional = parameter.required ? '' : '?';
      return `${indent(level + 2)}${escapeKey(parameter.name)}${optional}: ${emitSchema(parameter.schema ?? {}, level + 2)};`;
    });
    groupLines.push(`${indent(level + 1)}${escapeKey(groupName)}: {
${props.join('\n')}
${indent(level + 1)}};`);
  }
  return `${indent(level)}parameters: {
${groupLines.join('\n')}
${indent(level)}};`;
}

function emitResponses(responses, level) {
  const lines = Object.entries(responses ?? {}).map(([statusCode, response]) => {
    const content = response?.content ? `content: ${emitContent(response.content, level + 2)};` : 'content?: never;';
    return `${indent(level + 1)}${JSON.stringify(statusCode)}: {
${indent(level + 2)}${content}
${indent(level + 1)}};`;
  });
  if (!lines.length) return 'Record<string, never>';
  return `{
${lines.join('\n')}
${indent(level)}}`;
}

function emitOperation(operation, level) {
  const parts = [];
  const parametersBlock = emitParameters(operation.parameters, level + 1);
  if (parametersBlock) parts.push(parametersBlock);
  const requestBodyBlock = emitRequestBody(operation.requestBody, level + 1);
  if (requestBodyBlock) parts.push(requestBodyBlock);
  parts.push(`${indent(level + 1)}responses: ${emitResponses(operation.responses, level + 1)};`);
  return `{
${parts.join('\n')}
${indent(level)}}`;
}

const componentLines = schemaNames.map((name) => `${indent(2)}${JSON.stringify(name)}: ${emitSchema(schema.components.schemas[name], 2)};`);
const pathLines = routeEntries.map(([pathKey, operations]) => {
  const opLines = Object.entries(operations ?? {}).map(([method, operation]) => `${indent(2)}${method}: ${emitOperation(operation, 2)};`);
  return `${indent(1)}${JSON.stringify(normalizePathKey(pathKey))}: {
${opLines.join('\n')}
${indent(1)}};`;
});

const generatedContent = `/* eslint-disable */
// Generated by frontend/scripts/generate-openapi-types.mjs from frontend/openapi.json.
// Do not edit manually.

export interface components {
${indent(1)}schemas: {
${componentLines.join('\n')}
${indent(1)}};
}

export interface paths {
${pathLines.join('\n')}
}

export type SuccessStatusCode = \`${'${2}${string}'}\`;

type JsonBody<Content> = Content extends { 'application/json': infer Json } ? Json : never;

export type SuccessJson<Operation> = Operation extends { responses: infer Responses }
  ? {
      [Status in Extract<keyof Responses, SuccessStatusCode>]: Responses[Status] extends { content: infer Content }
        ? JsonBody<Content>
        : never;
    }[Extract<keyof Responses, SuccessStatusCode>]
  : never;
`;

const contractMetaContent = `// Generated by frontend/scripts/generate-openapi-types.mjs\n`
  + `export const OPENAPI_SNAPSHOT_HASH = '${hash}' as const;\n`
  + `export const OPENAPI_ROUTE_COUNT = ${routeEntries.length} as const;\n`
  + `export const OPENAPI_OPERATION_COUNT = ${operationIds.length} as const;\n`
  + `export const OPENAPI_OPERATION_IDS = ${JSON.stringify(operationIds)} as const;\n`;

const aliasMap = [
  ['HealthDependency', "components['schemas']['DependencyHealthResponse']"],
  ['ReadyState', "components['schemas']['DependenciesResponse']"],
  ['TaskListItem', "components['schemas']['TaskListItemResponse']"],
  ['SolutionRegistryItem', "components['schemas']['SolutionRegistryItemResponse']"],
  ['VerificationProtocolRegistryItem', "components['schemas']['VerificationProtocolRegistryItemResponse']"],
  ['ClarificationQuestionItem', "components['schemas']['ClarificationQuestionItem']"],
  ['ClarificationAnswer', "components['schemas']['ClarificationAnswerResponse']"],
  ['ClarificationRequest', "components['schemas']['ClarificationRequestResponse']"],
  ['GenerationRunRef', "components['schemas']['GenerationRunRefResponse']"],
  ['TaskSnapshot', "components['schemas']['TaskSnapshotResponse']"],
  ['GenerationRun', "components['schemas']['GenerationRunResponse']"],
  ['GenerationRunAccepted', "components['schemas']['GenerationRunAcceptedResponse']"],
  ['GenerationClarificationRequired', "components['schemas']['GenerationClarificationRequiredResponse']"],
  ['SolutionSectionSourceRef', "components['schemas']['SolutionSectionSourceRefResponse']"],
  ['SolutionSection', "components['schemas']['SolutionSectionResponse']"],
  ['SolutionSectionAssessment', "components['schemas']['SolutionSectionAssessmentResponse']"],
  ['SolutionArchitectureEntity', "components['schemas']['SolutionArchitectureEntityResponse']"],
  ['SolutionArchitectureRelation', "components['schemas']['SolutionArchitectureRelationResponse']"],
  ['SolutionArchitectureModel', "components['schemas']['SolutionArchitectureModelResponse']"],
  ['SolutionArchitectureModelEnvelope', "components['schemas']['SolutionArchitectureModelEnvelope']"],
  ['SolutionComponentInterface', "components['schemas']['SolutionComponentInterfaceResponse']"],
  ['SolutionComponent', "components['schemas']['SolutionComponentResponse']"],
  ['SolutionIntegration', "components['schemas']['SolutionIntegrationResponse']"],
  ['SolutionListItem', "components['schemas']['SolutionListItemResponse']"],
  ['SolutionRisk', "components['schemas']['SolutionRiskResponse']"],
  ['SolutionVerificationRunRef', "components['schemas']['SolutionVerificationRunRefResponse']"],
  ['PublicationRevision', "components['schemas']['PublicationRevisionResponse']"],
  ['SnapshotSummary', "components['schemas']['SnapshotSummaryResponse']"],
  ['Solution', "components['schemas']['SolutionResponse']"],
  ['RenderedSolution', "components['schemas']['SolutionRenderedResponse']"],
  ['VerificationRun', "components['schemas']['VerificationRunResponse']"],
  ['VerificationBasisDocument', "components['schemas']['VerificationBasisDocumentResponse']"],
  ['VerificationFinding', "components['schemas']['VerificationFindingResponse']"],
  ['VerificationProtocolViolation', "components['schemas']['VerificationProtocolViolationResponse']"],
  ['VerificationProtocolViolationsEnvelope', "components['schemas']['VerificationProtocolViolationsEnvelope']"],
  ['VerificationProtocol', "components['schemas']['VerificationProtocolResponse']"],
  ['RenderedVerificationProtocol', "components['schemas']['VerificationProtocolRenderedResponse']"],
  ['ActiveKnowledgeVersion', "components['schemas']['app__schemas__mvp__KnowledgeVersionResponse']"],
  ['KnowledgeBase', "components['schemas']['KnowledgeBaseResponse']"],
  ['KnowledgeBaseDocument', "components['schemas']['KnowledgeBaseDocumentResponse']"],
  ['Source', "components['schemas']['SourceResponse']"],
  ['SourceDocument', "components['schemas']['SourceDocumentResponse']"],
  ['KnowledgeBundleImportResult', "components['schemas']['KnowledgeBundleImportResponse']"],
  ['DocumentChunk', "components['schemas']['DocumentChunkResponse']"],
  ['DocumentSnapshot', "components['schemas']['DocumentSnapshotResponse']"],
  ['ExtractedKnowledgeItem', "components['schemas']['ExtractedKnowledgeItemResponse']"],
  ['DocumentMemory', "components['schemas']['DocumentMemoryResponse']"],
  ['KnowledgeNotification', "components['schemas']['KnowledgeNotificationResponse']"],
  ['KnowledgeVersion', "components['schemas']['app__schemas__knowledge__KnowledgeVersionResponse']"],
  ['KnowledgeUpdateRun', "components['schemas']['KnowledgeUpdateRunResponse']"],
  ['OperationItem', "components['schemas']['OperationJournalItemResponse']"],
  ['OperationStep', "components['schemas']['OperationStepResponse']"],
  ['AuditEvent', "components['schemas']['AuditEventResponse']"],
  ['OperationDetail', "components['schemas']['OperationDetailResponse']"],
  ['OperationMetrics', "components['schemas']['OperationMetricsResponse']"],
  ['SolutionSectionAssessmentsEnvelope', "components['schemas']['SolutionSectionAssessmentsEnvelope']"],
];

const aliasLines = aliasMap.map(([name, target]) => `export type ${name} = ${target};`);
const apiTypesContent = `/* eslint-disable */
// Generated by frontend/scripts/generate-openapi-types.mjs from frontend/openapi.json.
// Do not edit manually, except for the UI-only KnowledgeScope helpers below.

import type { components, paths, SuccessJson } from '../generated/openapi';

export type TaskStatus = string;
export type RunStatus = string;
export type SolutionStatus = string;
export type ProtocolStatus = string;
export type ProtocolSummaryStatus = string;
export type Severity = string;

export interface KnowledgeScopeVersionSnapshot {
  knowledge_version_id?: string | null;
  knowledge_base_id?: string | null;
  knowledge_base_code?: string | null;
  version_code?: string | null;
  status?: string | null;
  created_at?: string | null;
  activated_at?: string | null;
  source_scope?: string | null;
  source_count?: number | null;
  document_count?: number | null;
  basis_document_count?: number | null;
  missing_required_packages?: string[];
  basis_documents?: Array<Record<string, unknown>>;
}

export interface KnowledgeScopeDocumentSnapshot {
  mode?: string | null;
  document_count?: number | null;
  selected_document_ids?: string[];
  effective_document_ids?: string[];
  selected_documents?: Array<Record<string, unknown>>;
}

export interface KnowledgeScope {
  mandatory_version?: KnowledgeScopeVersionSnapshot | null;
  selected_user_version?: KnowledgeScopeVersionSnapshot | null;
  effective_version_ids: string[];
  selected_generation_version_id?: string | null;
  basis_documents?: Array<Record<string, unknown>>;
  document_scope?: KnowledgeScopeDocumentSnapshot | null;
  snapshot_hash?: string | null;
}

export type GenerationDispatch = SuccessJson<paths['/tasks/{task_id}/generation-runs']['post']>;

${aliasLines.join('\n')}
`;

fs.mkdirSync(path.dirname(generatedPath), { recursive: true });
fs.mkdirSync(path.dirname(metaPath), { recursive: true });
fs.mkdirSync(path.dirname(apiTypesPath), { recursive: true });
fs.writeFileSync(generatedPath, generatedContent, 'utf8');
fs.writeFileSync(metaPath, contractMetaContent, 'utf8');
fs.writeFileSync(apiTypesPath, apiTypesContent, 'utf8');
console.log(`Updated ${path.relative(root, generatedPath)}`);
console.log(`Updated ${path.relative(root, metaPath)}`);
console.log(`Updated ${path.relative(root, apiTypesPath)}`);
