import { Component, Input, Output, EventEmitter, HostListener, ElementRef } from '@angular/core';
import { CommonModule } from '@angular/common';

export interface DropdownOption {
  value: string | number;
  label: string;
  icon?: string;
}

@Component({
  selector: 'app-dropdown',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './dropdown.component.html',
  styleUrl: './dropdown.component.scss',
})
export class DropdownComponent {
  @Input() options: DropdownOption[] = [];
  @Input() value: string | number = '';
  @Input() placeholder = 'Select...';
  @Input() searchable = false;
  @Input() size: 'default' | 'sm' = 'default';
  @Output() valueChange = new EventEmitter<string | number>();

  isOpen = false;
  searchTerm = '';

  get selectedOption(): DropdownOption | undefined {
    return this.options.find((o) => o.value === this.value);
  }

  get filteredOptions(): DropdownOption[] {
    if (!this.searchTerm) return this.options;
    const term = this.searchTerm.toLowerCase();
    return this.options.filter((o) => o.label.toLowerCase().includes(term));
  }

  constructor(private el: ElementRef) {}

  toggle(): void {
    this.isOpen = !this.isOpen;
    if (!this.isOpen) this.searchTerm = '';
  }

  select(opt: DropdownOption): void {
    this.value = opt.value;
    this.valueChange.emit(opt.value);
    this.isOpen = false;
    this.searchTerm = '';
  }

  onSearch(event: Event): void {
    this.searchTerm = (event.target as HTMLInputElement).value;
  }

  @HostListener('document:click', ['$event'])
  onClickOutside(event: Event): void {
    if (!this.el.nativeElement.contains(event.target)) {
      this.isOpen = false;
      this.searchTerm = '';
    }
  }
}
