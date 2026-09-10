import crypto from 'crypto';
import { SupabaseClient } from '@supabase/supabase-js';

export interface CustomerOnboardingInput {
  name: string;
  industry?: string;
  freightSpendEst?: number;
  contactEmail: string;
  contactRole?: 'owner' | 'ap_clerk';
  remitToName?: string;
  remitToAddress?: string;
  customSlug?: string;
}

export interface OnboardingResult {
  success: boolean;
  customerId?: string;
  slug?: string;
  inboundEmail?: string;
  disputeCcEmail?: string;
  error?: string;
}

/**
 * Sanitizes a company name into a URL-friendly, email-compliant slug.
 * e.g., "Acme Machine & Supply Co." -> "acme-machine-supply-co"
 */
export function generateSlug(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48);
}

/**
 * Onboards a customer organization (<10 min onboarding target).
 * Creates customer record, provisions inbound slug, and registers primary user.
 */
export async function onboardCustomer(
  input: CustomerOnboardingInput,
  supabase: SupabaseClient
): Promise<OnboardingResult> {
  if (!input.name || !input.contactEmail) {
    return { success: false, error: 'Customer name and contact email are required' };
  }

  let slug = input.customSlug ? generateSlug(input.customSlug) : generateSlug(input.name);
  if (!slug) slug = `org-${crypto.randomUUID().slice(0, 8)}`;

  // Ensure slug uniqueness
  const { data: existingSlug } = await supabase
    .from('customers')
    .select('id')
    .eq('slug', slug)
    .maybeSingle();

  if (existingSlug) {
    slug = `${slug}-${crypto.randomUUID().slice(0, 4)}`;
  }

  const customerId = crypto.randomUUID();

  // 1. Insert customer record
  const { data: customer, error: custError } = await supabase
    .from('customers')
    .insert({
      id: customerId,
      name: input.name,
      slug: slug,
      industry: input.industry || 'Manufacturing',
      freight_spend_est: input.freightSpendEst || 0.00,
      status: 'active'
    })
    .select('id, slug')
    .single();

  if (custError) {
    return { success: false, error: `Customer creation failed: ${custError.message}` };
  }

  // 2. Register primary user
  const userId = crypto.randomUUID();
  const { error: userError } = await supabase
    .from('users')
    .insert({
      id: userId,
      customer_id: customer.id,
      email: input.contactEmail.toLowerCase().trim(),
      role: input.contactRole || 'owner'
    });

  if (userError) {
    return { success: false, error: `Primary user creation failed: ${userError.message}` };
  }

  const inboundEmail = `${customer.slug}@in.rateguard.app`;
  const disputeCcEmail = `disputes+${customer.slug}@in.rateguard.app`;

  return {
    success: true,
    customerId: customer.id,
    slug: customer.slug,
    inboundEmail,
    disputeCcEmail
  };
}
