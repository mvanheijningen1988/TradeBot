import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../services/auth.service';

export const authGuard: CanActivateFn = (_route, state) => {
  const auth = inject(AuthService);
  const router = inject(Router);

  if (auth.isAuthenticated()) {
    const requiresPasswordChange = auth.mustChangePassword();
    if (requiresPasswordChange && state.url !== '/change-password') {
      return router.parseUrl('/change-password');
    }
    if (!requiresPasswordChange && state.url === '/change-password') {
      return router.parseUrl('/');
    }
    return true;
  }
  router.navigate(['/login']);
  return false;
};
