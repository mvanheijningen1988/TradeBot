import { Routes } from '@angular/router';
import { authGuard } from './core/auth.guard';

export const routes: Routes = [
  { path: 'login', loadComponent: () => import('./pages/login/login.component').then(m => m.LoginComponent) },
  {
    path: 'change-password',
    loadComponent: () => import('./pages/change-password/change-password.component').then(m => m.ChangePasswordComponent),
    canActivate: [authGuard],
  },
  {
    path: '',
    loadComponent: () => import('./layout/layout.component').then(m => m.LayoutComponent),
    canActivate: [authGuard],
    children: [
      { path: '', loadComponent: () => import('./pages/dashboard/dashboard.component').then(m => m.DashboardComponent) },
      { path: 'news', loadComponent: () => import('./pages/news/news.component').then(m => m.NewsComponent) },
      { path: 'bots/new', loadComponent: () => import('./pages/bot-create/bot-create.component').then(m => m.BotCreateComponent) },
      { path: 'workers', loadComponent: () => import('./pages/workers/workers.component').then(m => m.WorkersComponent) },
      { path: 'settings', loadComponent: () => import('./pages/settings/settings.component').then(m => m.SettingsComponent) },
      { path: 'diagnostics', loadComponent: () => import('./pages/diagnostics/diagnostics.component').then(m => m.DiagnosticsComponent) },
    ],
  },
  { path: '**', redirectTo: '' },
];
