import type { RouteObject } from 'react-router'

import { AlertsPage } from '../features/alerts/AlertsPage'
import { AuditPage } from '../features/audit/AuditPage'
import { LoginPage } from '../features/auth/LoginPage'
import { DashboardPage } from '../features/dashboard/DashboardPage'
import { MappingPage } from '../features/mapping/MappingPage'
import { MastersPage } from '../features/masters/MastersPage'
import { NcDetailPage } from '../features/ncs/NcDetailPage'
import { NcListPage } from '../features/ncs/NcListPage'
import { ReportDetailPage } from '../features/reports/ReportDetailPage'
import { ReportsPage } from '../features/reports/ReportsPage'
import { SettingsPage } from '../features/settings/SettingsPage'
import { SpcPage } from '../features/spc/SpcPage'
import { Layout } from './layout'
import { NotFoundPage } from './NotFoundPage'
import { ToastShell } from './toast'

export const routes: RouteObject[] = [
  {
    element: <ToastShell />,
    children: [
      { path: '/login', element: <LoginPage /> },
      {
        path: '/',
        element: <Layout />,
        children: [
          { index: true, element: <DashboardPage /> },
          { path: 'reports', element: <ReportsPage /> },
          { path: 'reports/:id', element: <ReportDetailPage /> },
          { path: 'ncs', element: <NcListPage /> },
          { path: 'ncs/:id', element: <NcDetailPage /> },
          { path: 'alerts', element: <AlertsPage /> },
          { path: 'spc', element: <SpcPage /> },
          { path: 'mapping', element: <MappingPage /> },
          { path: 'audit', element: <AuditPage /> },
          { path: 'settings', element: <SettingsPage /> },
          { path: 'masters', element: <MastersPage /> },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
]
