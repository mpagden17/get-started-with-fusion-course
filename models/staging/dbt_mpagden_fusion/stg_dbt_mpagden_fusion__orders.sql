

with source as (

    select * from {{ source('dbt_mpagden_fusion', 'orders') }}

),

renamed as (

    select
        order_id,
        location_id,
        customer_id,
        subtotal_cents,
        tax_paid_cents,
        order_total_cents,
        subtotal,
        tax_paid,
        order_total,
        order_date,
        order_cost,
        order_items_subtotal,
        count_food_items,
        count_drink_items,
        count_order_items,
        is_food_order,
        is_drink_order,
        customer_order_number

    from source

)

select * from renamed

