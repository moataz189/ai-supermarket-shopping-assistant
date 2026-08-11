from app.ingestion.feeds import rami_levy, shufersal


def test_shufersal_skips_item_with_unrecognized_unit_keeps_the_rest(caplog):
    xml = """<Root>
      <StoreID>413</StoreID>
      <Items>
        <Item>
          <ItemCode>1</ItemCode>
          <ItemName>good item</ItemName>
          <ItemPrice>5.0</ItemPrice>
          <Quantity>1</Quantity>
          <UnitQty>גרם</UnitQty>
        </Item>
        <Item>
          <ItemCode>2</ItemCode>
          <ItemName>bad item</ItemName>
          <ItemPrice>3.0</ItemPrice>
          <Quantity>1</Quantity>
          <UnitQty>1</UnitQty>
        </Item>
      </Items>
    </Root>""".encode()

    products = shufersal.parse(xml)

    assert [p.item_code for p in products] == ["1"]
    assert "unrecognized UnitQty" in caplog.text
    assert "item_code=2" in caplog.text


def test_rami_levy_skips_item_with_unrecognized_unit_keeps_the_rest(caplog):
    xml = """<Root>
      <StoreId>39</StoreId>
      <Items>
        <Item>
          <ItemCode>1</ItemCode>
          <ItemNm>good item</ItemNm>
          <ItemPrice>5.0</ItemPrice>
          <Quantity>1</Quantity>
          <UnitQty>יח'</UnitQty>
        </Item>
        <Item>
          <ItemCode>2</ItemCode>
          <ItemNm>bad item</ItemNm>
          <ItemPrice>3.0</ItemPrice>
          <Quantity>1</Quantity>
          <UnitQty>1</UnitQty>
        </Item>
      </Items>
    </Root>""".encode()

    products = rami_levy.parse(xml)

    assert [p.item_code for p in products] == ["1"]
    assert "unrecognized UnitQty" in caplog.text
    assert "item_code=2" in caplog.text
