

with source as (

    select * from {{ source('dbt_mpagden_fusion', 'products') }}

),

renamed as (

    select
        product_id,
        product_name,
        product_type,
        product_description,
        product_price,
        is_food_item,
        is_drink_item

    from source

)

select * from renamed

