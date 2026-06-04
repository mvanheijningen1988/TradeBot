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
  @Input() maxVisible = 50;
  @Output() valueChange = new EventEmitter<string | number>();

  isOpen = false;
  searchTerm = '';
  scrollOffset = 0;
  readonly itemHeight = 32;

  get selectedOption(): DropdownOption | undefined {
    return this.options.find((o) => o.value === this.value);
  }

  get filteredOptions(): DropdownOption[] {
    if (!this.searchTerm) return this.options;
    const term = this.searchTerm.toLowerCase();
    return this.options.filter((o) => o.label.toLowerCase().includes(term));
  }

  get visibleOptions(): DropdownOption[] {
    return this.filteredOptions.slice(this.scrollOffset, this.scrollOffset + this.maxVisible);
  }

  constructor(private el: ElementRef) {}

  toggle(): void {
    this.isOpen = !this.isOpen;
    if (!this.isOpen) {
      this.searchTerm = '';
      this.scrollOffset = 0;
    }
  }

  select(opt: DropdownOption): void {
    this.value = opt.value;
    this.valueChange.emit(opt.value);
    this.isOpen = false;
    this.searchTerm = '';
    this.scrollOffset = 0;
  }

  onSearch(event: Event): void {
    this.searchTerm = (event.target as HTMLInputElement).value;
    this.scrollOffset = 0;
  }

  onScroll(event: Event): void {
    const el = event.target as HTMLElement;
    const newOffset = Math.floor(el.scrollTop / this.itemHeight);
    if (newOffset !== this.scrollOffset) {
      this.scrollOffset = newOffset;
    }
  }

  @HostListener('document:click', ['$event'])
  onClickOutside(event: Event): void {
    if (!this.el.nativeElement.contains(event.target)) {
      this.isOpen = false;
      this.searchTerm = '';
    }
  }
}
