
{{
    config(
        materialized = 'table'
    )
}}

select 
    convert(string,c_custkey) as stringkey,
    c_name,
    c_address,
    c_nationkey,
    c_phone, 
    dlog10(c_acctbal) as actbalbaseten,
    dlog10(c_acctbal) as actbalbaseten,
    c_mktsegment,
    c_comment,
    getdate() as hoy,
    GETDATE AS get_date_caps_test,
    sysdate() AS sys_date_col_test,
    SYSDATE() AS sys_date_caps_col_test,
    ISNULL(test, test_is_null) AS null_test_col_caps,
    ISNULL(test, test_is_null) AS null_test_col_caps,
    isnull(test, 'test_is_null') AS null_test_col,
    first_value(
            case
                when cte_contract_pricings.contract_years = 3
                     then cte_contract_pricings.id
            end ignore nulls
        ) over (
            partition by
                cte_contract_pricings.upstart_id
            order by
                cte_contract_pricings.created_at, cte_contract_pricings.id
            rows between unbounded preceding and unbounded following
        ) as test_syntax_change
from
    redshift_sample_data.tpch_rs1.customer
ORDER BY colC,colB DESC