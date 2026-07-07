

with source as (

    select * from {{ source('dbt_mpagden_fusion', 'customers') }}

),

renamed as (

    select
        customer_id,
        customer_name,
        count_lifetime_orders,
        first_order_date,
        last_order_date,
        lifetime_spend_pretax,
        lifetime_tax_paid,
        lifetime_spend,
        test_column,
        customer_type

    from source

)

select * from renamed

