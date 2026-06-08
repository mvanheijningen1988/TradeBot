import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-change-password',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './change-password.component.html',
  styleUrl: './change-password.component.scss',
})
export class ChangePasswordComponent {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  currentPassword = '';
  newPassword = '';
  confirmPassword = '';
  error = '';
  success = '';

  onChangePassword(): void {
    this.error = '';
    this.success = '';

    if (this.newPassword !== this.confirmPassword) {
      this.error = 'The new passwords do not match.';
      return;
    }

    this.auth.changePassword(this.currentPassword, this.newPassword).subscribe({
      next: () => {
        this.success = 'Password updated. Redirecting...';
        this.router.navigate(['/']);
      },
      error: (err) => {
        this.error = err?.error?.detail || 'Failed to change password.';
      },
    });
  }
}