#!/usr/bin/env python3
"""
Seed pricing plans for the briefing subscription system.
Run with: python scripts/seed_pricing_plans.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import PricingPlan


PRICING_PLANS = [
    {
        'code': 'starter',
        'name': 'Starter',
        'description': 'Perfect for getting started with one focused brief',
        'price_monthly': 1200,  # £12
        'price_yearly': None,
        'max_briefs': 1,
        'max_sources': 10,
        'max_recipients': 10,
        'max_editors': 1,
        'allow_document_uploads': False,
        'allow_custom_branding': False,
        'allow_approval_workflow': False,
        'allow_slack_integration': False,
        'allow_api_access': False,
        'priority_processing': False,
        'is_organisation': False,
        'display_order': 1,
    },
    {
        'code': 'professional',
        'name': 'Professional',
        'description': 'Stay on top of everything that matters',
        'price_monthly': 2500,  # £25
        'price_yearly': 25000,  # £250
        'max_briefs': 10,
        'max_sources': -1,  # Unlimited (fair use)
        'max_recipients': 50,
        'max_editors': 1,
        'allow_document_uploads': True,
        'allow_custom_branding': False,
        'allow_approval_workflow': False,
        'allow_slack_integration': False,
        'allow_api_access': False,
        'priority_processing': True,
        'is_organisation': False,
        'display_order': 2,
    },
    {
        'code': 'team',
        'name': 'Team',
        'description': 'Align your team with shared intelligence',
        'price_monthly': 30000,  # £300
        'price_yearly': None,
        'max_briefs': -1,  # Unlimited (fair use)
        'max_sources': -1,
        'max_recipients': 500,
        'max_editors': 5,
        'allow_document_uploads': True,
        'allow_custom_branding': True,
        'allow_approval_workflow': True,
        'allow_slack_integration': True,
        'allow_api_access': False,
        'priority_processing': True,
        'is_organisation': True,
        'display_order': 3,
    },
    {
        'code': 'enterprise',
        'name': 'Enterprise',
        'description': 'For organisations with complex needs',
        'price_monthly': 200000,  # £2,000
        'price_yearly': None,
        'max_briefs': -1,
        'max_sources': -1,
        'max_recipients': -1,
        'max_editors': -1,
        'allow_document_uploads': True,
        'allow_custom_branding': True,
        'allow_approval_workflow': True,
        'allow_slack_integration': True,
        'allow_api_access': True,
        'priority_processing': True,
        'is_organisation': True,
        'display_order': 4,
    },
]


def seed_pricing_plans():
    """Create or update pricing plans in the database."""
    app = create_app()
    
    with app.app_context():
        for plan_data in PRICING_PLANS:
            code = plan_data['code']
            existing = PricingPlan.query.filter_by(code=code).first()
            
            if existing:
                print(f"Updating plan: {code}")
                for key, value in plan_data.items():
                    setattr(existing, key, value)
            else:
                print(f"Creating plan: {code}")
                plan = PricingPlan(**plan_data)
                db.session.add(plan)
        
        db.session.commit()
        print("\nPricing plans seeded successfully!")
        
        plans = PricingPlan.query.order_by(PricingPlan.display_order).all()
        print(f"\nTotal plans: {len(plans)}")
        for plan in plans:
            print(f"  - {plan.code}: £{plan.price_monthly/100}/month")


if __name__ == '__main__':
    seed_pricing_plans()
