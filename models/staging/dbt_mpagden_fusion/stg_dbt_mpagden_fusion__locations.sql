

with source as (

    select * from {{ source('dbt_mpagden_fusion', 'locations') }}

),

renamed as (

    select
        location_id,
        location_name,
        tax_rate,
        opened_date

    from source

)

select * from renamed

