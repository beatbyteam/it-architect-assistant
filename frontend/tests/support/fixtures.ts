export const isoNow = '2026-04-04T09:00:00Z';

export const activeKnowledgeVersion = {
  knowledge_version_id: 'kv-1',
  version_no: 'KV-20260404-001',
  created_at: isoNow,
  activated_at: isoNow,
};

export const dashboardTask = {
  task_id: 'task-1',
  title: 'Архитектура сервиса согласования',
  state: 'ready_for_generation',
  created_at: isoNow,
  updated_at: isoNow,
};

export const solution = {
  solution_version_id: 'solution-1',
  solution_title: 'Архитектура сервиса согласования',
  task_id: 'task-1',
  state: 'published',
  created_at: isoNow,
  published_at: isoNow,
  publication_revision_no: 'rev-3',
  sections: [
    {
      section_code: 'general_information',
      title: '1. Общие сведения',
      body_markdown: 'Контекст и цель.',
      sort_order: 1,
      source_refs: [],
    },
  ],
  verification_runs: [
    {
      verification_run_id: 'verification-run-1',
      protocol_id: 'protocol-1',
      state: 'completed',
      current_stage: 'publishing',
      diagnostics: { operation_id: 'op-verification-1' },
    },
  ],
  explainability: {
    retrieval_summary: { policy_id: 'hybrid-default', selected_counts: { vector: 3 } },
    basis_documents: [
      {
        document_id: 'doc-1',
        title: 'TOGAF baseline',
        role_code: 'togaf',
        required_flag: true,
        fragment_count: 2,
        sections: ['general_information'],
      },
    ],
    section_coverage: [
      { section_code: 'general_information', title: '1. Общие сведения', source_ref_count: 1, basis_document_count: 1 },
    ],
    evidence_coverage: { section_count: 1, total_source_refs: 1, sections_with_evidence: 1, sections_without_evidence: [] },
    structured_model: { version: 'sectioned-architecture-model.v1', section_summaries: [] },
  },
  snapshot_summary: { knowledge_snapshot: { selected_generation_version_id: 'kv-1' } },
  knowledge_scope: { selected_generation_version_id: 'kv-1', effective_version_ids: ['kv-1'] },
  section_assessments: [
    {
      section_assessment_id: 'sa-1',
      section_code: 'general_information',
      heading: '1. Общие сведения',
      status: 'ready',
      score: 0.95,
      observed_signal_groups: ['context'],
      missing_signal_groups: [],
      reasons: [],
      allowed_archimate_elements: [],
      fallback_applied: false,
      details: {},
      sort_order: 1,
    },
  ],
  architecture_model: {
    version: 'sectioned-architecture-model.v1',
    entities: [
      {
        architecture_entity_id: 'entity-1',
        entity_key: 'service',
        display_name: 'Approval Service',
        source_kind: 'component',
        section_code: 'application_architecture',
        archimate_layer: 'application',
        archimate_element_code: 'application_component',
        archimate_element_title: 'Application Component',
        normalized_flag: true,
        confidence: 0.9,
        entity_metadata: {},
        sort_order: 1,
      },
    ],
    relations: [],
    section_summaries: [],
    diagnostics: {},
  },
  publication_history: [],
};

export const task = {
  task_id: 'task-1',
  title: 'Архитектура сервиса согласования',
  raw_text: 'Нужно подготовить архитектурное решение для сервиса согласования артефактов.',
  state: 'ready_for_generation',
  created_at: isoNow,
  updated_at: isoNow,
  next_action_hint: 'Можно запускать подготовку решения.',
  readiness_assessment: { missing_inputs: [] },
  clarification_requests: [],
  generation_runs: [
    {
      generation_run_id: 'generation-run-1',
      solution_version_id: 'solution-1',
      state: 'completed',
      current_stage: 'publishing',
      diagnostics: { operation_id: 'op-generation-1' },
    },
  ],
};

export const generationRun = {
  generation_run_id: 'generation-run-1',
  state: 'completed',
  current_stage: 'publishing',
  solution_version_id: 'solution-1',
  diagnostics: { operation_id: 'op-generation-1' },
};

export const verificationRun = {
  verification_run_id: 'verification-run-1',
  protocol_id: 'protocol-1',
  state: 'completed',
  current_stage: 'publishing',
  diagnostics: { operation_id: 'op-verification-1' },
  knowledge_scope: { selected_generation_version_id: 'kv-1', effective_version_ids: ['kv-1'] },
};

export const protocol = {
  protocol_id: 'protocol-1',
  verification_run_id: 'verification-run-1',
  solution_version_id: 'solution-1',
  summary_text: 'Есть замечания по структурному разделу.',
  summary_status: 'passed_with_comments',
  created_at: isoNow,
  diagnostics: { operation_id: 'op-verification-1' },
  findings: [
    {
      finding_id: 'finding-1',
      rule_id: 'VR-STR-01',
      rule_name: 'VR-STR-01',
      rule_group: 'structure',
      severity: 'major',
      status: 'warning',
      finding_text: 'Контекст описан неполно.',
      related_section_ref: 'general_information',
    },
  ],
  explainability: {
    basis_package: { basis_document_count: 1, required_basis_count: 1, basis_documents: [] },
    evidence_coverage: { finding_count: 1, findings_with_evidence: 1, findings_without_evidence: [] },
    rule_execution: { executed_rule_groups: ['structure'], validation_scope: 'full' },
  },
  snapshot_summary: { rulebook_version: 'vr.v1' },
  knowledge_scope: { selected_generation_version_id: 'kv-1', effective_version_ids: ['kv-1'] },
  compliance_summary: { groups: { structure: { warning: 1 } } },
  publication_history: [],
};

export const knowledgeBase = {
  knowledge_base_id: 'kb-1',
  name: 'ERP baseline',
  kind: 'user_managed',
  status: 'active',
  description: 'Проектная база требований.',
  selected_for_generation: true,
  active_version_no: 'KV-20260404-001',
  selected_knowledge_version_no: 'KV-20260404-001',
  latest_sync_at: isoNow,
  latest_sync_status: 'completed',
  last_sync_error_count: 0,
  document_count: 12,
  active_source_count: 2,
  last_sync_duration_sec: 32,
};

export const mandatoryBase = {
  knowledge_base_id: 'kb-system',
  name: 'TOGAF + ArchiMate 3.2',
  kind: 'system_mandatory',
  status: 'active',
  description: 'Обязательная системная база.',
  selected_for_generation: false,
  active_version_no: 'KV-BASE-001',
  selected_knowledge_version_no: 'KV-BASE-001',
  latest_sync_at: isoNow,
  latest_sync_status: 'completed',
  last_sync_error_count: 0,
  document_count: 8,
  active_source_count: 1,
  last_sync_duration_sec: 12,
};

export const knowledgeSource = {
  source_id: 'source-1',
  knowledge_base_id: 'kb-1',
  name: 'Confluence export',
  source_type: 'url_list',
};

export const knowledgeNotification = {
  notification_id: 'notification-1',
  knowledge_base_id: 'kb-1',
  knowledge_base_name: 'ERP baseline',
  update_run_id: 'run-1',
  title: 'Обновление завершено',
  message: 'Новая версия знаний активирована.',
  status: 'success',
  created_at: isoNow,
};

export const metrics = {
  knowledge_updates: { count: 3 },
};
