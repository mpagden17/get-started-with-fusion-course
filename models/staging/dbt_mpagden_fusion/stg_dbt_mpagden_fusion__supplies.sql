

with source as (

    select * from {{ source('dbt_mpagden_fusion', 'supplies') }}

),

renamed as (

    select
        supply_uuid,
        supply_id,
        product_id,
        supply_name,
        supply_cost,
        is_perishable_supply

    from source

)

select * from renamed

