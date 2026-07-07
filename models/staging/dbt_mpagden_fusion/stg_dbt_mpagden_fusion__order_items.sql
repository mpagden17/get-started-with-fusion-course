

with source as (

    select * from {{ source('dbt_mpagden_fusion', 'order_items') }}

),

renamed as (

    select
        order_item_id,
        order_id,
        product_id,
        order_date,
        product_name,
        product_price,
        is_food_item,
        is_drink_item,
        product_type,
        supply_cost

    from source

)

select * from renamed

