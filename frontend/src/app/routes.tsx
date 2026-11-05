import type { RouteObject } from 'react-router'

import { DashboardPage } from '../features/dashboard/DashboardPage'
import { Layout } from './layout'
import { NotFoundPage } from './NotFoundPage'

export const routes: RouteObject[] = [
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]
