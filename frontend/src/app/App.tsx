import { ReactNode } from 'react';
import { BrowserRouter, MemoryRouter, Navigate, NavLink, Outlet, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DashboardPage } from '../pages/DashboardPage';
import { ExternalArchitectureCheckPage } from '../pages/ExternalArchitectureCheckPage';
import { NewTaskPage } from '../pages/NewTaskPage';
import { TaskWorkspacePage } from '../pages/TaskWorkspacePage';
import { SolutionPage } from '../pages/SolutionPage';
import { ProtocolPage } from '../pages/ProtocolPage';
import { KnowledgePage } from '../pages/KnowledgePage';
import { KnowledgeBaseDetailsPage } from '../pages/KnowledgeBaseDetailsPage';
import { KnowledgeDocumentPage } from '../pages/KnowledgeDocumentPage';
import { OperationsPage } from '../pages/OperationsPage';
import { RegistryPage } from '../pages/RegistryPage';
import { OperationDetailsPage } from '../pages/OperationDetailsPage';

export function createAppQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: 1,
        refetchOnWindowFocus: false,
      },
    },
  });
}

const queryClient = createAppQueryClient();

function navClassName({ isActive }: { isActive: boolean }) {
  return `nav-item${isActive ? ' active' : ''}`;
}

function AppLayout() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <strong>Помощник ИТ-архитектора</strong>
        </div>

        <nav className="nav-list">
          <NavLink to="/external-check" className={navClassName}>Проверка архитектуры</NavLink>
          <NavLink to="/" end className={navClassName}>Главная</NavLink>
          <NavLink to="/tasks/new" className={navClassName}>Новая задача</NavLink>
          <NavLink to="/registry" className={navClassName}>Задачи и результаты</NavLink>
          <NavLink to="/knowledge" className={navClassName}>База знаний</NavLink>
          <NavLink to="/operations" className={navClassName}>Журнал</NavLink>
        </nav>
      </aside>

      <main className="main-shell">
        <div className="page stack">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<AppLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="tasks/new" element={<NewTaskPage />} />
        <Route path="external-check" element={<ExternalArchitectureCheckPage />} />
        <Route path="registry" element={<RegistryPage />} />
        <Route path="tasks/:taskId" element={<TaskWorkspacePage />} />
        <Route path="solutions/:solutionId" element={<SolutionPage />} />
        <Route path="protocols/:protocolId" element={<ProtocolPage />} />
        <Route path="knowledge" element={<KnowledgePage />} />
        <Route path="knowledge/bases/:knowledgeBaseId" element={<KnowledgeBaseDetailsPage />} />
        <Route path="knowledge/documents/:documentId" element={<KnowledgeDocumentPage />} />
        <Route path="operations" element={<OperationsPage />} />
        <Route path="operations/:operationId" element={<OperationDetailsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

interface AppProvidersProps {
  children: ReactNode;
  queryClient?: QueryClient;
  initialEntries?: string[];
  routerMode?: 'browser' | 'memory';
}

function AppProviders({
  children,
  queryClient: providedQueryClient,
  initialEntries = ['/'],
  routerMode = 'browser',
}: AppProvidersProps) {
  const activeClient = providedQueryClient ?? queryClient;
  const router = routerMode === 'memory'
    ? <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>
    : <BrowserRouter>{children}</BrowserRouter>;

  return <QueryClientProvider client={activeClient}>{router}</QueryClientProvider>;
}

interface AppProps {
  queryClient?: QueryClient;
  initialEntries?: string[];
  routerMode?: 'browser' | 'memory';
}

export function App({ queryClient: providedQueryClient, initialEntries, routerMode = 'browser' }: AppProps = {}) {
  return (
    <AppProviders queryClient={providedQueryClient} initialEntries={initialEntries} routerMode={routerMode}>
      <AppRoutes />
    </AppProviders>
  );
}
