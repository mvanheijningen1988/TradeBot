import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { BehaviorSubject, Observable, tap } from 'rxjs';
import { environment } from '../../environments/environment';

export interface User {
  id: number;
  username: string;
  role: string;
  language: string;
  time_display: string;
  must_change_password: boolean;
}

export interface LoginResponse {
  access_token: string;
  must_change_password: boolean;
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly user$ = new BehaviorSubject<User | null>(null);
  private readonly requirePasswordResetKey = 'force_reset';

  get currentUser$(): Observable<User | null> {
    return this.user$.asObservable();
  }

  get currentUserValue(): User | null {
    return this.user$.value;
  }

  mustChangePassword(): boolean {
    const currentUser = this.currentUserValue;
    if (currentUser) {
      return currentUser.must_change_password;
    }
    return localStorage.getItem(this.requirePasswordResetKey) === '1';
  }

  isAuthenticated(): boolean {
    const token = localStorage.getItem('access_token');
    if (!token) return false;
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      if (payload.exp && payload.exp * 1000 < Date.now()) {
        this.logout();
        return false;
      }
      return true;
    } catch {
      return false;
    }
  }

  login(username: string, password: string): Observable<LoginResponse> {
    return this.http
      .post<LoginResponse>(`${environment.apiUrl}/auth/login`, {
        username,
        password,
      })
      .pipe(
        tap((res) => {
          localStorage.setItem('access_token', res.access_token);
          if (res.must_change_password) {
            this.enablePasswordChangeFlag();
          } else {
            this.clearPasswordChangeFlag();
          }
          this.loadUser();
        })
      );
  }

  changePassword(currentPassword: string, newPassword: string): Observable<{ detail: string }> {
    return this.http
      .put<{ detail: string }>(`${environment.apiUrl}/auth/password`, {
        current_password: currentPassword,
        new_password: newPassword,
      })
      .pipe(
        tap(() => {
          this.clearPasswordChangeFlag();
          this.loadUser();
        })
      );
  }

  logout(): void {
    localStorage.removeItem('access_token');
    this.clearPasswordChangeFlag();
    this.user$.next(null);
  }

  loadUser(): void {
    this.http
      .get<User>(`${environment.apiUrl}/auth/me`)
      .subscribe({
        next: (user) => {
          this.user$.next(user);
          if (user.must_change_password) {
            this.enablePasswordChangeFlag();
          } else {
            this.clearPasswordChangeFlag();
          }
        },
        error: () => this.logout(),
      });
  }

  private enablePasswordChangeFlag(): void {
    localStorage.setItem(this.requirePasswordResetKey, '1');
  }

  private clearPasswordChangeFlag(): void {
    localStorage.removeItem(this.requirePasswordResetKey);
  }
}
